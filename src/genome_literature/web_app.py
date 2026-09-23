"""Local web GUI for the 3D Genome & Deep Learning Literature Hub.

Launch with ``python run.py`` (or ``python -m genome_literature serve``) and
open http://localhost:8686.  The server binds to 127.0.0.1 by default
(override with GENOME_HUB_HOST) and state-changing requests must carry the
``X-Requested-With: 3DGenomeHub`` header, so other websites cannot trigger
fetches or emails.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from . import __version__, config
from .analyzer import analyze_papers
from .categorizer import get_statistics
from .email_notifier import send_digest_email
from .pipeline import last_new_papers, run_pipeline
from .readme_generator import write_outputs
from .search import search_papers, to_bibtex, to_csv
from .storage import load_papers, load_state
from .summarizer import generate_digest

logger = logging.getLogger(__name__)

_job_lock = threading.Lock()
_status: dict[str, Any] = {"status": "idle", "message": "Ready", "job": None, "log": deque(maxlen=200)}
_cache: dict[str, Any] = {"mtime": None, "papers": []}
_cache_lock = threading.Lock()


def get_papers() -> list[dict[str, Any]]:
    """Papers from disk, re-read only when papers.json changes."""
    path = config.PAPERS_JSON
    mtime = path.stat().st_mtime if path.exists() else None
    with _cache_lock:
        if mtime != _cache["mtime"]:
            _cache["papers"] = load_papers() if mtime else []
            _cache["mtime"] = mtime
        return _cache["papers"]


def _progress(msg: str) -> None:
    _status["message"] = msg
    _status["log"].append(msg)


def start_job(name: str, fn: Callable[[], str]) -> bool:
    """Run ``fn`` in a background thread unless another job is running."""
    if not _job_lock.acquire(blocking=False):
        return False
    _status.update(status="running", job=name, message=f"{name} started…")
    _status["log"].clear()

    def runner() -> None:
        try:
            _status.update(status="done", message=fn())
        except Exception as exc:
            logger.exception("%s failed", name)
            _status.update(status="error", message=f"{name} failed: {exc}")
        finally:
            _status["job"] = None
            _job_lock.release()

    threading.Thread(target=runner, daemon=True).start()
    return True


def _pipeline_job(**kwargs: Any) -> Callable[[], str]:
    def job() -> str:
        r = run_pipeline(progress=_progress, **kwargs)
        errors = len(r.get("fetch_errors") or [])
        msg = (f"Done: {r.get('new_count', 0)} new papers ({r.get('relevant_count', 0)} relevant of "
               f"{r.get('fetched_count', 0)} candidates). Total: {r.get('total_count', 0)}.")
        if errors:
            msg += f" {errors} queries failed (network/API) — see log."
            for e in r["fetch_errors"][:10]:
                _status["log"].append(f"ERROR {e['source']}: {e['error'][:160]}")
        return msg
    return job


class GUIHandler(BaseHTTPRequestHandler):
    server_version = f"3DGenomeHub/{__version__}"

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug("%s - %s", self.address_string(), format % args)

    # -- routing -----------------------------------------------------------
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        routes = {
            "/": self._home,
            "/api/status": self._api_status,
            "/api/papers": lambda: self._json(get_papers()),
            "/api/stats": self._api_stats,
            "/api/digest": self._api_digest,
            "/api/analysis": lambda: self._json(analyze_papers(get_papers())),
            "/api/search": lambda: self._json(search_papers(get_papers(), qs.get("q", [""])[0], limit=200)),
            "/api/export": lambda: self._export(qs.get("format", ["csv"])[0]),
            "/api/export-csv": lambda: self._export("csv"),
        }
        handler = routes.get(parsed.path)
        if handler:
            handler()
        else:
            self._error(404, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8") if length else ""
        if self.headers.get("X-Requested-With") != "3DGenomeHub":
            self._error(403, "Missing X-Requested-With header")
            return
        if parsed.path == "/api/search":
            query = parse_qs(body).get("q", [""])[0]
            self._json(search_papers(get_papers(), query, limit=200))
            return
        actions: dict[str, tuple[str, Callable[[], str]]] = {
            "/api/fetch": ("Update", _pipeline_job(skip_email=True)),
            "/api/run-pipeline": ("Full pipeline", _pipeline_job()),
            "/api/backfill": ("Backfill", _pipeline_job(backfill=True, skip_email=True)),
            "/api/update-readme": ("README update", self._job_readme),
            "/api/send-email": ("Email digest", self._job_email),
        }
        if parsed.path not in actions:
            self._error(404, "Not found")
            return
        name, fn = actions[parsed.path]
        if start_job(name, fn):
            self._json({"ok": True, "message": f"{name} started…"})
        else:
            self._json({"ok": False, "message": f"Busy: {_status.get('job')} is still running"})

    # -- jobs --------------------------------------------------------------
    @staticmethod
    def _job_readme() -> str:
        papers = get_papers()
        written = write_outputs(papers, last_new_papers(papers))
        return f"README.md and {len(written) - 1} topic pages updated ({len(papers)} papers)."

    @staticmethod
    def _job_email() -> str:
        papers = get_papers()
        new = last_new_papers(papers)
        if not new:
            return "No new papers from the last update — nothing to send."
        ok = send_digest_email(new, generate_digest(new, papers))
        return "Email digest sent." if ok else "Email not sent — check SMTP settings in .env."

    # -- endpoints -----------------------------------------------------------
    def _api_status(self) -> None:
        self._json({k: (list(v) if isinstance(v, deque) else v) for k, v in _status.items()})

    def _api_stats(self) -> None:
        papers = get_papers()
        state = load_state()
        stats = get_statistics(papers)
        stats.update(
            last_run=state.get("last_run"),
            new_ids=state.get("last_new_ids") or [],
            runs=(state.get("runs") or [])[-10:],
            tracks=config.TRACKS,
            category_descriptions={k: v["description"] for k, v in config.CATEGORIES.items()},
            version=__version__,
        )
        self._json(stats)

    def _api_digest(self) -> None:
        papers = get_papers()
        new = last_new_papers(papers)
        digest = generate_digest(new, papers)
        self._json({"summary_text": digest["summary_text"], "new_count": len(new)})

    def _export(self, fmt: str) -> None:
        papers = get_papers()
        if fmt == "bib":
            self._download(to_bibtex(papers), "application/x-bibtex", "3DGenomeHub_papers.bib")
        elif fmt == "json":
            self._download(json.dumps(papers, ensure_ascii=False, indent=1), "application/json", "3DGenomeHub_papers.json")
        else:
            self._download("﻿" + to_csv(papers), "text/csv", "3DGenomeHub_papers.csv")

    # -- responses -----------------------------------------------------------
    def _home(self) -> None:
        self._send(200, HOME_HTML.encode("utf-8"), "text/html; charset=utf-8")

    def _json(self, data: Any) -> None:
        self._send(200, json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"), "application/json; charset=utf-8")

    def _download(self, text: str, ctype: str, filename: str) -> None:
        self._send(200, text.encode("utf-8"), f"{ctype}; charset=utf-8",
                   {"Content-Disposition": f"attachment; filename={filename}"})

    def _error(self, code: int, message: str) -> None:
        self._send(code, json.dumps({"error": message}).encode("utf-8"), "application/json")

    def _send(self, code: int, payload: bytes, ctype: str, headers: dict[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)


def make_server(host: str | None = None, port: int | None = None, tries: int = 10) -> ThreadingHTTPServer:
    host = host or config.WEB_HOST
    port = port or config.WEB_PORT
    last_error: OSError | None = None
    for candidate in range(port, port + tries):
        try:
            return ThreadingHTTPServer((host, candidate), GUIHandler)
        except OSError as exc:
            last_error = exc
    raise OSError(f"No free port in {port}-{port + tries - 1}: {last_error}")


def start_server(port: int | None = None, open_browser: bool = True, host: str | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stderr)
    server = make_server(host, port)
    bound_host, bound_port = server.server_address[:2]
    url = f"http://{'localhost' if bound_host in ('127.0.0.1', '0.0.0.0') else bound_host}:{bound_port}"
    print(f"\n{'=' * 60}\n  3D Genome & Deep Learning Literature Hub v{__version__}\n  Web GUI: {url}\n"
          f"  Press Ctrl+C to stop\n{'=' * 60}\n")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        server.server_close()


HOME_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>3D Genome Literature Hub</title>
<style>
:root{--bg:#0b1020;--panel:#121a30;--panel2:#0e1528;--line:#23304d;--text:#e5e9f2;--muted:#8b97b0;--dim:#5d6a85;
--accent:#818cf8;--accent2:#6366f1;--ml:#a78bfa;--comp:#38bdf8;--exp:#94a3b8;--good:#34d399;--warn:#fbbf24;--bad:#f87171}
*{box-sizing:border-box;margin:0;padding:0}
body{font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
a{color:#a5b4fc;text-decoration:none}a:hover{text-decoration:underline}
button{font:inherit;cursor:pointer}
header{padding:22px 20px 18px;background:linear-gradient(120deg,#1e2a5a,#3b1f6b 60%,#5b1a4a);border-bottom:1px solid var(--line)}
header h1{font-size:22px;font-weight:700;letter-spacing:.2px}
header p{color:#c7cff0;font-size:13px;margin-top:4px}
.wrap{max-width:1360px;margin:0 auto;padding:14px 16px 40px}
.actions{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px}
.btn{border:1px solid var(--line);background:var(--panel);color:var(--text);padding:8px 13px;border-radius:8px;font-weight:600;font-size:13px}
.btn:hover{border-color:var(--accent)}
.btn.primary{background:var(--accent2);border-color:var(--accent2)}
.btn:disabled{opacity:.45;cursor:not-allowed}
.status{display:flex;align-items:center;gap:10px;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:9px 12px;margin-bottom:14px;font-size:13px;color:var(--muted)}
.dot{width:9px;height:9px;border-radius:50%;background:var(--exp);flex:none}
.dot.running{background:var(--warn);animation:pulse 1s infinite}.dot.done{background:var(--good)}.dot.error{background:var(--bad)}
@keyframes pulse{50%{opacity:.3}}
.status .msg{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.status button{background:none;border:none;color:var(--accent);font-size:12px}
#log{display:none;background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:10px;margin:-8px 0 14px;font:12px/1.5 ui-monospace,Menlo,Consolas,monospace;color:var(--muted);max-height:220px;overflow:auto;white-space:pre-wrap}
.grid{display:grid;grid-template-columns:290px minmax(0,1fr);gap:14px}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:13px;margin-bottom:12px}
.panel h3{font-size:12px;text-transform:uppercase;letter-spacing:.6px;color:var(--muted);margin-bottom:9px}
.kpis{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.kpi{background:var(--panel2);border-radius:8px;padding:9px;text-align:center}
.kpi b{display:block;font-size:21px;color:var(--accent)}.kpi span{font-size:11px;color:var(--dim)}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{border:1px solid var(--line);background:var(--panel2);color:var(--text);border-radius:999px;padding:4px 10px;font-size:12px}
.chip.on{background:var(--accent2);border-color:var(--accent2)}
.list{max-height:330px;overflow:auto}
.item{display:flex;justify-content:space-between;gap:6px;padding:5px 8px;border-radius:6px;cursor:pointer;font-size:12.5px}
.item:hover{background:var(--panel2)}.item.on{background:#27305a}
.item .n{color:var(--accent);font-weight:600}
label.f{display:block;font-size:12px;color:var(--muted);margin:8px 0 4px}
select,input[type=text],input[type=search]{width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--text);border-radius:7px;padding:7px 9px;font:inherit;font-size:13px}
.row{display:flex;gap:6px}
.check{display:flex;align-items:center;gap:7px;font-size:12.5px;color:var(--text);margin-top:6px}
.searchbar{display:flex;gap:8px;margin-bottom:10px}
.searchbar input{font-size:14px;padding:10px 12px}
.toolbar{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px;color:var(--muted);font-size:13px}
.toolbar select{width:auto}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:13px 15px;margin-bottom:9px}
.card:hover{border-color:#3a4a78}
.card h2{font-size:15px;line-height:1.35;margin:4px 0 4px}
.meta{font-size:12.5px;color:var(--muted)}
.badges{display:flex;gap:5px;flex-wrap:wrap;align-items:center}
.b{font-size:10.5px;font-weight:700;border-radius:4px;padding:1px 6px;letter-spacing:.3px}
.b.ml{background:#2e1f5e;color:var(--ml)}.b.computational{background:#0c2f45;color:var(--comp)}.b.experimental{background:#27303f;color:#cbd5e1}
.b.new{background:#0f3d2c;color:var(--good)}.b.pre{background:#3d3212;color:var(--warn)}.b.cur{background:#4a1d3d;color:#f9a8d4}
.rel{margin-left:auto;font-size:11px;color:var(--dim)}
.tags{display:flex;flex-wrap:wrap;gap:5px;margin:7px 0 4px}
.tag{font-size:11px;border:1px solid var(--line);border-radius:4px;padding:1px 7px;background:var(--panel2);color:#c3cbe0;cursor:pointer}
.tag.m{color:var(--ml)}
.abs{font-size:12.8px;color:#a9b3c9;margin-top:5px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;cursor:pointer}
.abs.open{display:block}
.links{display:flex;flex-wrap:wrap;gap:12px;margin-top:7px;font-size:12.5px}
.pager{display:flex;justify-content:center;gap:5px;flex-wrap:wrap;margin-top:12px}
.pager button{background:var(--panel);border:1px solid var(--line);color:var(--text);border-radius:6px;padding:5px 11px;font-size:12px}
.pager button.on{background:var(--accent2);border-color:var(--accent2)}
.empty{text-align:center;color:var(--dim);padding:50px 10px}
.modal{display:none;position:fixed;inset:0;background:rgba(3,6,15,.82);z-index:10;overflow:auto;padding:24px 12px}
.modal.open{display:block}
.sheet{max-width:1100px;margin:0 auto;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:22px;position:relative}
.sheet h2{font-size:19px;margin-bottom:14px}.sheet h3{font-size:14px;margin:18px 0 8px;color:#dbe2f3}
.close{position:absolute;top:10px;right:14px;background:none;border:none;color:var(--muted);font-size:26px}
pre.sum{background:var(--panel2);border-radius:8px;padding:12px;font:12px/1.55 ui-monospace,Menlo,Consolas,monospace;color:#c7d2fe;white-space:pre-wrap;overflow:auto}
.bar{display:flex;align-items:center;gap:8px;font-size:12.5px;margin:3px 0}
.bar span:first-child{width:190px;flex:none;color:#cbd5e1}
.bar .track{flex:1;background:var(--panel2);height:14px;border-radius:3px;overflow:hidden}
.bar .fill{height:100%;background:linear-gradient(90deg,var(--accent2),var(--ml))}
.bar .v{width:44px;text-align:right;color:var(--accent)}
table.t{width:100%;border-collapse:collapse;font-size:12.5px}
table.t th,table.t td{padding:6px 7px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
table.t th{color:var(--muted);font-weight:600}
.scroll{overflow-x:auto}
td.h{text-align:center;color:#fff;min-width:44px}
footer{color:var(--dim);text-align:center;font-size:12px;padding:10px}
</style>
</head>
<body>
<header>
  <h1>3D Genome × Deep Learning Literature Hub</h1>
  <p id="sub">Loading…</p>
</header>
<div class="wrap">
  <div class="actions">
    <button class="btn primary" data-act="/api/fetch" title="Fetch papers published since the last update, filter, merge and save">Update now</button>
    <button class="btn" data-act="/api/run-pipeline" title="Update + regenerate README/topic pages + send email digest">Full pipeline</button>
    <button class="btn" data-act="/api/backfill" title="Relevance-ranked search across all years (slower)">Backfill all years</button>
    <button class="btn" data-act="/api/update-readme">Rebuild README</button>
    <button class="btn" data-act="/api/send-email">Send email digest</button>
    <button class="btn" id="btnAnalysis">Landscape analysis</button>
    <a class="btn" href="/api/export?format=csv">Export CSV</a>
    <a class="btn" href="/api/export?format=bib">Export BibTeX</a>
  </div>
  <div class="status"><span class="dot" id="dot"></span><span class="msg" id="msg">Ready</span><button id="logBtn">show log</button></div>
  <div id="log"></div>

  <div class="grid">
    <aside>
      <div class="panel">
        <h3>Overview</h3>
        <div class="kpis">
          <div class="kpi"><b id="kTotal">–</b><span>papers</span></div>
          <div class="kpi"><b id="kMl">–</b><span>AI / ML</span></div>
          <div class="kpi"><b id="kRecent">–</b><span>since last year</span></div>
          <div class="kpi"><b id="kNew">–</b><span>new in last update</span></div>
        </div>
      </div>
      <div class="panel">
        <h3>Track</h3>
        <div class="chips" id="tracks"></div>
      </div>
      <div class="panel">
        <h3>Topics</h3>
        <div class="list" id="cats"></div>
      </div>
      <div class="panel">
        <h3>Architectures</h3>
        <div class="list" id="methods" style="max-height:230px"></div>
      </div>
      <div class="panel">
        <h3>Filters</h3>
        <label class="f">Source</label>
        <select id="source"><option value="">All databases</option></select>
        <label class="f">Years</label>
        <div class="row"><select id="yFrom"><option value="">From</option></select><select id="yTo"><option value="">To</option></select></div>
        <label class="check"><input type="checkbox" id="onlyNew"> New in last update</label>
        <label class="check"><input type="checkbox" id="onlyPre"> Preprints only</label>
        <label class="check"><input type="checkbox" id="onlyCur"> Landmark papers only</label>
        <label class="check"><input type="checkbox" id="onlyAbs"> With abstract</label>
        <button class="btn" id="reset" style="margin-top:10px;width:100%">Reset filters</button>
      </div>
    </aside>

    <main>
      <div class="searchbar"><input type="search" id="q" placeholder='Search title, abstract, authors, venue, tags — e.g. Hi-C transformer, "loop extrusion"'></div>
      <div class="toolbar">
        <span id="info">Loading…</span>
        <select id="sort">
          <option value="relevance">Sort: relevance</option>
          <option value="newest">Sort: newest</option>
          <option value="oldest">Sort: oldest</option>
          <option value="cited">Sort: most cited</option>
          <option value="title">Sort: title</option>
        </select>
      </div>
      <div id="list"></div>
      <div class="pager" id="pager"></div>
    </main>
  </div>
</div>
<footer>3DGenomeHub <span id="ver"></span> · <a href="https://github.com/Yin-Shen/3DGenomeHub" target="_blank" rel="noopener">GitHub</a></footer>

<div class="modal" id="modal"><div class="sheet"><button class="close" id="closeModal" aria-label="Close">×</button>
  <h2>Research landscape: 3D genome × deep learning</h2><div id="analysis">Loading…</div></div></div>

<script>
const PER_PAGE = 25;
const S = {papers: [], stats: {}, newIds: new Set(), f: {q: '', track: '', cat: '', method: '', source: '', yFrom: 0, yTo: 9999, onlyNew: false, onlyPre: false, onlyCur: false, onlyAbs: false}, sort: 'relevance', page: 1, view: []};
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const TRACK_NAMES = {ml: 'AI / ML', computational: 'Computational', experimental: 'Experimental & Biology'};
let poll = null;

async function getJSON(url) { const r = await fetch(url); if (!r.ok) throw new Error(r.status); return r.json(); }

async function loadAll() {
  const [papers, stats] = await Promise.all([getJSON('/api/papers'), getJSON('/api/stats')]);
  S.papers = papers; S.stats = stats; S.newIds = new Set(stats.new_ids || []);
  renderSidebar(); apply();
}

function renderSidebar() {
  const s = S.stats;
  $('kTotal').textContent = s.total_papers || 0;
  $('kMl').textContent = s.ml_papers || 0;
  $('kRecent').textContent = s.recent_papers || 0;
  $('kNew').textContent = S.newIds.size;
  $('ver').textContent = s.version ? 'v' + s.version : '';
  $('sub').textContent = s.total_papers
    ? `${s.total_papers} papers · ${s.ml_papers} AI/ML · ${s.preprints} preprints · last update ${s.last_run ? s.last_run.slice(0, 10) : 'never'}`
    : 'Database is empty — click "Update now" (or "Backfill all years" for full coverage).';
  const tracks = [['', 'All', s.total_papers || 0], ...Object.entries(s.by_track || {}).map(([k, v]) => [k, TRACK_NAMES[k] || k, v])];
  $('tracks').innerHTML = tracks.map(([k, name, n]) => `<button class="chip${S.f.track === k ? ' on' : ''}" data-track="${esc(k)}">${esc(name)} (${n})</button>`).join('');
  const desc = s.category_descriptions || {};
  $('cats').innerHTML = Object.entries(s.by_category || {}).map(([c, n]) =>
    `<div class="item${S.f.cat === c ? ' on' : ''}" data-cat="${esc(c)}" title="${esc(desc[c] || c)}"><span>${esc(c)}</span><span class="n">${n}</span></div>`).join('') || '<span class="meta">No papers yet</span>';
  $('methods').innerHTML = Object.entries(s.by_method || {}).map(([m, n]) =>
    `<div class="item${S.f.method === m ? ' on' : ''}" data-method="${esc(m)}"><span>${esc(m)}</span><span class="n">${n}</span></div>`).join('') || '<span class="meta">No AI/ML papers yet</span>';
  const src = $('source'), cur = S.f.source;
  src.innerHTML = '<option value="">All databases</option>' + Object.entries(s.by_source || {}).map(([k, n]) => `<option value="${esc(k)}">${esc(k)} (${n})</option>`).join('');
  src.value = cur;
  const years = Object.keys(s.by_year || {}).sort((a, b) => b - a);
  for (const id of ['yFrom', 'yTo']) {
    const el = $(id), v = el.value;
    el.innerHTML = `<option value="">${id === 'yFrom' ? 'From' : 'To'}</option>` + years.map(y => `<option>${y}</option>`).join('');
    el.value = v;
  }
}

function tokens(q) { return [...q.matchAll(/"([^"]+)"|(\S+)/g)].map(m => (m[1] || m[2]).toLowerCase()); }

function searchScore(p, terms) {
  const title = (p.title || '').toLowerCase();
  const tags = [...(p.categories || []), ...(p.dl_methods || []), ...(p.tools || []), ...(p.keywords || [])].join(' ').toLowerCase();
  const other = [p.abstract, (p.authors || []).join(' '), p.journal, p.doi].join(' ').toLowerCase();
  let score = 0;
  for (const t of terms) {
    if (title.includes(t)) score += 3; else if (tags.includes(t)) score += 2; else if (other.includes(t)) score += 1; else return -1;
  }
  return score;
}

function apply() {
  const f = S.f, terms = tokens(f.q);
  let rows = [];
  for (const p of S.papers) {
    if (f.track && p.track !== f.track) continue;
    if (f.cat && !(p.categories || []).includes(f.cat)) continue;
    if (f.method && !(p.dl_methods || []).includes(f.method)) continue;
    if (f.source && !(p.sources || [p.source]).includes(f.source)) continue;
    if ((p.year || 0) < f.yFrom || (p.year || 0) > f.yTo) continue;
    if (f.onlyNew && !S.newIds.has(p.id)) continue;
    if (f.onlyPre && !p.is_preprint) continue;
    if (f.onlyCur && !p.curated) continue;
    if (f.onlyAbs && !p.abstract) continue;
    let score = 0;
    if (terms.length) { score = searchScore(p, terms); if (score < 0) continue; }
    rows.push([score + (p.relevance || 0) / 100, p]);
  }
  const by = {
    relevance: (a, b) => b[0] - a[0] || (b[1].date || '').localeCompare(a[1].date || ''),
    newest: (a, b) => (b[1].date || '').localeCompare(a[1].date || ''),
    oldest: (a, b) => (a[1].date || '').localeCompare(b[1].date || ''),
    cited: (a, b) => (b[1].citations || 0) - (a[1].citations || 0),
    title: (a, b) => (a[1].title || '').localeCompare(b[1].title || ''),
  };
  rows.sort(by[S.sort]);
  S.view = rows.map(r => r[1]);
  const active = [f.track && TRACK_NAMES[f.track], f.cat, f.method, f.source, f.q && `"${f.q}"`].filter(Boolean);
  $('info').textContent = `${S.view.length} papers` + (active.length ? ' · ' + active.join(' · ') : '');
  render();
}

function card(p) {
  const authors = (p.authors || []).length > 3 ? p.authors.slice(0, 3).join(', ') + ' et al.' : (p.authors || []).join(', ') || 'Unknown authors';
  const badges = [`<span class="b ${esc(p.track)}">${esc(TRACK_NAMES[p.track] || p.track)}</span>`];
  if (S.newIds.has(p.id)) badges.push('<span class="b new">NEW</span>');
  if (p.is_preprint) badges.push('<span class="b pre">PREPRINT</span>');
  if (p.curated) badges.push('<span class="b cur">LANDMARK</span>');
  const tags = (p.categories || []).map(c => `<span class="tag" data-cat="${esc(c)}">${esc(c)}</span>`)
    .concat((p.dl_methods || []).map(m => `<span class="tag m" data-method="${esc(m)}">${esc(m)}</span>`)).join('');
  const links = [];
  if (p.doi) links.push(`<a href="https://doi.org/${esc(p.doi)}" target="_blank" rel="noopener">DOI</a>`);
  if (p.pmid) links.push(`<a href="https://pubmed.ncbi.nlm.nih.gov/${esc(p.pmid)}/" target="_blank" rel="noopener">PubMed</a>`);
  if (p.arxiv_id) links.push(`<a href="https://arxiv.org/abs/${esc(p.arxiv_id)}" target="_blank" rel="noopener">arXiv</a>`);
  if (p.pdf_url) links.push(`<a href="${esc(p.pdf_url)}" target="_blank" rel="noopener">PDF</a>`);
  links.push(`<a href="https://scholar.google.com/scholar?q=${encodeURIComponent(p.title || '')}" target="_blank" rel="noopener">Scholar</a>`);
  const cites = p.citations ? ` · ${p.citations} citations` : '';
  return `<article class="card">
    <div class="badges">${badges.join('')}<span class="rel" title="Relevance score (0-100)">relevance ${p.relevance ?? '–'}</span></div>
    <h2>${p.url ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.title)}</a>` : esc(p.title)}</h2>
    <div class="meta">${esc(authors)} · <i>${esc(p.journal || 'n/a')}</i> · ${esc(p.date || p.year || '')}${cites}</div>
    <div class="tags">${tags}</div>
    ${p.abstract ? `<p class="abs" title="Click to expand">${esc(p.abstract)}</p>` : ''}
    <div class="links">${links.join('')}</div>
  </article>`;
}

function render() {
  const pages = Math.max(1, Math.ceil(S.view.length / PER_PAGE));
  S.page = Math.min(S.page, pages);
  const slice = S.view.slice((S.page - 1) * PER_PAGE, S.page * PER_PAGE);
  $('list').innerHTML = slice.length ? slice.map(card).join('')
    : `<div class="empty">${S.papers.length ? 'No papers match the current filters.' : 'No papers yet — click <b>Update now</b> or <b>Backfill all years</b>.'}</div>`;
  const btn = (p, label, on) => `<button data-page="${p}" class="${on ? 'on' : ''}" ${p < 1 || p > pages ? 'disabled' : ''}>${label}</button>`;
  let html = '';
  if (pages > 1) {
    html += btn(S.page - 1, '‹ Prev');
    for (let i = 1; i <= pages; i++) {
      if (i === 1 || i === pages || Math.abs(i - S.page) <= 2) html += btn(i, i, i === S.page);
      else if (Math.abs(i - S.page) === 3) html += '<button disabled>…</button>';
    }
    html += btn(S.page + 1, 'Next ›');
  }
  $('pager').innerHTML = html;
}

function setFilter(key, value) {
  S.f[key] = S.f[key] === value ? '' : value; S.page = 1; renderSidebar(); apply();
}

document.addEventListener('click', e => {
  const t = e.target.closest('[data-track],[data-cat],[data-method],[data-page],[data-act],.abs');
  if (!t) return;
  if (t.classList.contains('abs')) { t.classList.toggle('open'); return; }
  if (t.dataset.act) { runAction(t.dataset.act); return; }
  if (t.dataset.page) { S.page = +t.dataset.page; render(); window.scrollTo({top: 0, behavior: 'smooth'}); return; }
  if ('track' in t.dataset) return setFilter('track', t.dataset.track);
  if (t.dataset.cat) return setFilter('cat', t.dataset.cat);
  if (t.dataset.method) return setFilter('method', t.dataset.method);
});

let qTimer = null;
$('q').addEventListener('input', e => { clearTimeout(qTimer); qTimer = setTimeout(() => { S.f.q = e.target.value.trim(); S.page = 1; apply(); }, 180); });
$('sort').addEventListener('change', e => { S.sort = e.target.value; apply(); });
$('source').addEventListener('change', e => { S.f.source = e.target.value; S.page = 1; apply(); });
$('yFrom').addEventListener('change', e => { S.f.yFrom = +e.target.value || 0; S.page = 1; apply(); });
$('yTo').addEventListener('change', e => { S.f.yTo = +e.target.value || 9999; S.page = 1; apply(); });
for (const id of ['onlyNew', 'onlyPre', 'onlyCur', 'onlyAbs']) $(id).addEventListener('change', e => { S.f[id] = e.target.checked; S.page = 1; apply(); });
$('reset').addEventListener('click', () => {
  S.f = {q: '', track: '', cat: '', method: '', source: '', yFrom: 0, yTo: 9999, onlyNew: false, onlyPre: false, onlyCur: false, onlyAbs: false};
  $('q').value = ''; for (const id of ['onlyNew', 'onlyPre', 'onlyCur', 'onlyAbs']) $(id).checked = false;
  $('yFrom').value = ''; $('yTo').value = ''; S.page = 1; renderSidebar(); apply();
});
$('logBtn').addEventListener('click', () => { const l = $('log'); const open = l.style.display === 'block'; l.style.display = open ? 'none' : 'block'; $('logBtn').textContent = open ? 'show log' : 'hide log'; });

function setStatus(d) {
  $('dot').className = 'dot ' + (d.status || 'idle');
  $('msg').textContent = d.message || 'Ready';
  $('log').textContent = (d.log || []).join('\n');
  $('log').scrollTop = $('log').scrollHeight;
  document.querySelectorAll('[data-act]').forEach(b => b.disabled = d.status === 'running');
}

async function runAction(url) {
  if (url === '/api/send-email' && !confirm('Send the email digest of the last update to all configured recipients?')) return;
  const r = await fetch(url, {method: 'POST', headers: {'X-Requested-With': '3DGenomeHub'}});
  const d = await r.json();
  setStatus({status: d.ok ? 'running' : 'error', message: d.message});
  if (d.ok && !poll) poll = setInterval(checkStatus, 1500);
}

async function checkStatus() {
  const d = await getJSON('/api/status').catch(() => null);
  if (!d) return;
  setStatus(d);
  if (d.status === 'running' && !poll) poll = setInterval(checkStatus, 1500);
  else if (d.status !== 'running' && poll) { clearInterval(poll); poll = null; loadAll(); }
}

function bars(obj, max = 15) {
  const entries = Object.entries(obj || {}).slice(0, max);
  const peak = Math.max(1, ...entries.map(e => e[1]));
  return entries.map(([k, v]) => `<div class="bar"><span>${esc(k)}</span><div class="track"><div class="fill" style="width:${Math.max(2, v / peak * 100)}%"></div></div><span class="v">${v}</span></div>`).join('');
}

async function showAnalysis() {
  $('modal').classList.add('open');
  $('analysis').textContent = 'Analyzing…';
  const a = await getJSON('/api/analysis').catch(e => ({error: String(e)}));
  if (a.error || !a.total_papers) { $('analysis').textContent = a.error || 'No papers to analyze yet.'; return; }
  let h = `<div class="kpis" style="grid-template-columns:repeat(4,1fr);margin-bottom:14px">
    <div class="kpi"><b>${a.total_papers}</b><span>papers</span></div><div class="kpi"><b>${a.dl_paper_count}</b><span>AI/ML papers</span></div>
    <div class="kpi"><b>${a.dl_ratio}%</b><span>AI/ML share</span></div><div class="kpi"><b>${Object.keys(a.dl_method_distribution || {}).length}</b><span>architecture families</span></div></div>`;
  h += `<pre class="sum">${esc(a.research_summary)}</pre>`;
  h += `<h3>Architectures used</h3>${bars(a.dl_method_distribution)}`;
  const years = Object.keys(a.trend_analysis || {}).sort((x, y) => y - x);
  if (years.length) {
    h += '<h3>Year by year</h3><div class="scroll"><table class="t"><tr><th>Year</th><th>Papers</th><th>AI/ML</th><th>AI/ML share</th><th>Top architectures</th></tr>';
    for (const y of years) { const t = a.trend_analysis[y]; h += `<tr><td>${y}</td><td>${t.total}</td><td>${t.ml}</td><td>${t.ml_share}%</td><td>${esc(Object.entries(t.top_methods).map(([m, c]) => `${m} (${c})`).join(', '))}</td></tr>`; }
    h += '</table></div>';
  }
  const cats = a.landscape_categories || [], methods = a.landscape_methods || [];
  if (cats.length && methods.length) {
    const peak = Math.max(1, ...methods.flatMap(m => cats.map(c => (a.landscape_matrix[m] || {})[c] || 0)));
    h += '<h3>Architecture × topic (AI/ML papers)</h3><div class="scroll"><table class="t"><tr><th>Topic</th>' + methods.map(m => `<th>${esc(m)}</th>`).join('') + '</tr>';
    for (const c of cats) {
      h += `<tr><td>${esc(c)}</td>` + methods.map(m => { const v = (a.landscape_matrix[m] || {})[c] || 0; return `<td class="h" style="background:rgba(129,140,248,${(v / peak * 0.85).toFixed(2)})">${v || ''}</td>`; }).join('') + '</tr>';
    }
    h += '</table></div>';
  }
  if ((a.topic_growth || []).length) {
    const color = {emerging: 'var(--good)', growing: 'var(--good)', steady: 'var(--muted)', slowing: 'var(--warn)'};
    h += '<h3>Topic momentum (last 24 months vs previous 24)</h3><div class="scroll"><table class="t"><tr><th>Topic</th><th>Total</th><th>Last 24 mo</th><th>Previous 24 mo</th><th>Change</th><th>Status</th></tr>';
    for (const g of a.topic_growth) h += `<tr><td>${esc(g.category)}</td><td>${g.total}</td><td>${g.last_24_months}</td><td>${g.previous_24_months}</td><td>${g.growth_pct == null ? '–' : (g.growth_pct > 0 ? '+' : '') + g.growth_pct + '%'}</td><td style="color:${color[g.status]}">${g.status}</td></tr>`;
    h += '</table></div>';
  }
  if ((a.hot_topics || []).length) {
    h += '<h3>Most active method × topic pairs (last 2 years)</h3>' + bars(Object.fromEntries(a.hot_topics.map(t => [t.topic, t.count])), 12);
  }
  if (Object.keys(a.tool_mentions || {}).length) {
    h += '<h3>Named tools and models</h3><div class="chips">' + Object.entries(a.tool_mentions).map(([t, c]) => `<span class="chip">${esc(t)} · ${c}</span>`).join('') + '</div>';
  }
  $('analysis').innerHTML = h;
}
$('btnAnalysis').addEventListener('click', showAnalysis);
$('closeModal').addEventListener('click', () => $('modal').classList.remove('open'));
$('modal').addEventListener('click', e => { if (e.target.id === 'modal') $('modal').classList.remove('open'); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') $('modal').classList.remove('open'); });

loadAll().catch(e => { $('list').innerHTML = `<div class="empty">Failed to load papers: ${esc(e)}</div>`; });
checkStatus();
</script>
</body>
</html>
"""
