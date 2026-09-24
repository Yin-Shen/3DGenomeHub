"""Local web app for the 3D Genome & Deep Learning Literature Hub.

Launch with ``python run.py`` (or ``python -m genome_literature serve``) and
open http://localhost:8686.  The page itself lives in ``web/`` (HTML, CSS,
JS).  The server binds to 127.0.0.1 by default (override with
GENOME_HUB_HOST) and state-changing requests must carry the
``X-Requested-With: 3DGenomeHub`` header, so other websites cannot trigger
fetches, emails or AI calls.  AI answers are streamed as server-sent events.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import parse_qs, quote, urlparse

from . import __version__, assistant, config, llm, notes, translator
from .categorizer import get_statistics
from .email_notifier import send_digest_email
from .pipeline import last_new_papers, run_pipeline
from .readme_generator import write_outputs
from .search import search_papers, to_bibtex, to_csv
from .storage import load_papers, load_state
from .summarizer import generate_digest

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent / "web"
LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1", "[::1]"}
STATIC_TYPES = {".html": "text/html", ".css": "text/css", ".js": "application/javascript", ".svg": "image/svg+xml"}

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


_tr_cache: dict[str, Any] = {"mtime": None, "data": {}}


def get_translations() -> dict[str, dict[str, Any]]:
    """Translation cache from disk, re-read only when translations.json changes."""
    path = config.TRANSLATIONS_JSON
    mtime = path.stat().st_mtime if path.exists() else None
    with _cache_lock:
        if mtime != _tr_cache["mtime"]:
            _tr_cache["data"] = translator.load_cache() if mtime else {}
            _tr_cache["mtime"] = mtime
        return _tr_cache["data"]


def papers_payload() -> list[dict[str, Any]]:
    return translator.attach_translations(get_papers(), get_translations())


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
    def _host_allowed(self) -> bool:
        """Reject DNS-rebinding requests: a loopback-bound server only answers to loopback host names."""
        if self.server.server_address[0] not in ("127.0.0.1", "::1", "localhost"):
            return True
        host = (self.headers.get("Host") or "").strip().lower()
        name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
        return name in LOOPBACK_NAMES

    def do_GET(self) -> None:
        if not self._host_allowed():
            self._error(403, "Forbidden host")
            return
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        arg = lambda name: qs.get(name, [""])[0]  # noqa: E731
        routes = {
            "/": lambda: self._static("index.html"),
            "/api/status": self._api_status,
            "/api/papers": lambda: self._json(papers_payload()),
            "/api/stats": self._api_stats,
            "/api/digest": self._api_digest,
            "/api/search": lambda: self._json(search_papers(get_papers(), arg("q"), limit=200)),
            "/api/export": lambda: self._export(arg("format") or "csv"),
            "/api/export-csv": lambda: self._export("csv"),
            "/api/ai/settings": lambda: self._json(llm.settings()),
            "/api/ai/notes": lambda: self._json({"notes": notes.list_notes()}),
            "/api/ai/note": lambda: self._api_note(arg("id")),
            "/api/ai/note-download": lambda: self._api_note_download(arg("id")),
            "/api/ai/interpretation": lambda: self._api_interpretation(arg("id")),
        }
        if parsed.path.startswith("/static/"):
            self._static(parsed.path[len("/static/"):])
            return
        handler = routes.get(parsed.path)
        if handler:
            handler()
        else:
            self._error(404, "Not found")

    def do_POST(self) -> None:
        if not self._host_allowed():
            self._error(403, "Forbidden host")
            return
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
        if parsed.path == "/api/translate":
            self._api_translate(body)
            return
        if parsed.path == "/api/translate-batch":
            self._api_translate_batch(body)
            return
        ai_routes: dict[str, Callable[[dict[str, Any]], None]] = {
            "/api/ai/settings": self._api_ai_settings,
            "/api/ai/test": self._api_ai_test,
            "/api/ai/run": self._api_ai_run,
            "/api/ai/chat": self._api_ai_chat,
            "/api/ai/chat-save": self._api_ai_chat_save,
            "/api/ai/note-delete": lambda data: self._json({"ok": notes.delete_note(str(data.get("id") or ""))}),
        }
        if parsed.path in ai_routes:
            try:
                data = json.loads(body or "{}")
            except ValueError:
                data = {}
            ai_routes[parsed.path](data if isinstance(data, dict) else {})
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

    # -- translation ---------------------------------------------------------
    @staticmethod
    def _requested_ids(body: str) -> list[str]:
        try:
            data = json.loads(body or "{}")
        except ValueError:
            return []
        ids = data.get("ids") or ([data["id"]] if data.get("id") else [])
        return [str(i) for i in ids][:200]

    def _api_translate(self, body: str) -> None:
        ids = self._requested_ids(body)
        paper = next((p for p in get_papers() if ids and p["id"] == ids[0]), None)
        if paper is None:
            self._json({"ok": False, "message": "Paper not found"})
            return
        try:
            entry = translator.translate_paper(paper)
        except translator.TranslationError as exc:
            self._json({"ok": False, "message": str(exc)})
            return
        self._json({"ok": True, "translation": entry})

    def _api_translate_batch(self, body: str) -> None:
        wanted = set(self._requested_ids(body))
        papers = [p for p in get_papers() if p["id"] in wanted]
        if not translator.is_configured():
            self._json({"ok": False, "message": "未配置 AI 接口：请点击右上角“设置 AI”填写 API Key"})
            return

        def job() -> str:
            stats = translator.translate_papers(papers, progress=_progress)
            msg = f"翻译完成：{stats['translated']} 篇"
            if stats["needs_review"]:
                msg += f"，其中 {stats['needs_review']} 篇标记为待校对"
            if stats["failed"]:
                msg += f"，{stats['failed']} 篇失败（{stats['errors'][0][:120]}）"
            return msg

        if start_job("Translation", job):
            self._json({"ok": True, "message": f"Translating {len(papers)} papers…"})
        else:
            self._json({"ok": False, "message": f"Busy: {_status.get('job')} is still running"})

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
            tracks=config.TRACKS,
            category_descriptions={k: v["description"] for k, v in config.CATEGORIES.items()},
            version=__version__,
            ai=llm.settings(),
            translated=len(get_translations()),
        )
        self._json(stats)

    # -- AI assistant --------------------------------------------------------
    def _papers_for(self, ids: Any) -> list[dict[str, Any]]:
        by_id = {p["id"]: p for p in get_papers()}
        wanted = [str(i) for i in (ids or []) if str(i) in by_id]
        return [by_id[i] for i in dict.fromkeys(wanted)]

    def _api_ai_settings(self, data: dict[str, Any]) -> None:
        values = {"LLM_API_BASE": data.get("base"), "LLM_MODEL": data.get("model"),
                  "LLM_REASONING_MODEL": data.get("reasoning_model")}
        values = {k: str(v).strip() for k, v in values.items() if v is not None}
        if data.get("api_key"):
            values["LLM_API_KEY"] = str(data["api_key"]).strip()
        base = values.get("LLM_API_BASE", config.LLM_API_BASE)
        if base and not base.startswith(("http://", "https://")):
            self._json({"ok": False, "message": "API 地址需以 http:// 或 https:// 开头"})
            return
        try:
            current = llm.save_settings(values)
        except OSError as exc:
            self._json({"ok": False, "message": f"无法写入 {config.ENV_FILE}: {exc}"})
            return
        self._json({"ok": True, "settings": current})

    def _api_ai_test(self, data: dict[str, Any]) -> None:
        try:
            self._json(llm.test_connection())
        except llm.LLMError as exc:
            self._json({"ok": False, "message": str(exc)})

    def _api_ai_run(self, data: dict[str, Any]) -> None:
        papers = self._papers_for(data.get("ids"))
        events = assistant.run_task(
            str(data.get("task") or ""), papers, question=str(data.get("question") or ""),
            deep=bool(data.get("deep")), use_fulltext=bool(data.get("use_fulltext", True)),
        )
        self._sse(events)

    def _api_ai_chat(self, data: dict[str, Any]) -> None:
        library = get_papers()
        context = self._papers_for(data.get("context_ids"))
        filter_ids = data.get("filter_ids")
        allowed = {str(i) for i in filter_ids} if isinstance(filter_ids, list) else None
        messages = data.get("messages") if isinstance(data.get("messages"), list) else []
        events = assistant.chat(
            messages, context, scope=str(data.get("scope") or "selection"), library=library, allowed=allowed,
            deep=bool(data.get("deep")), use_fulltext=bool(data.get("use_fulltext")),
        )
        self._sse(events)

    def _api_ai_chat_save(self, data: dict[str, Any]) -> None:
        messages = data.get("messages") if isinstance(data.get("messages"), list) else []
        if not messages:
            self._json({"ok": False, "message": "没有可保存的对话"})
            return
        note = assistant.save_conversation(str(data.get("title") or "AI 讨论"), messages,
                                           self._papers_for(data.get("context_ids")), model=config.LLM_MODEL)
        self._json({"ok": True, "note": note})

    def _api_note(self, note_id: str) -> None:
        found = notes.get_note(note_id)
        if not found:
            self._json({"note": None})
            return
        note, markdown = found
        self._json({"note": note, "body": notes.note_body(markdown), "markdown": markdown})

    def _api_note_download(self, note_id: str) -> None:
        found = notes.get_note(note_id)
        if not found:
            self._error(404, "Note not found")
            return
        note, markdown = found
        self._send(200, markdown.encode("utf-8"), "text/markdown; charset=utf-8",
                   {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(note['file'])}"})

    def _api_interpretation(self, paper_id: str) -> None:
        note = notes.latest_interpretation(paper_id)
        found = notes.get_note(note["id"]) if note else None
        if not found:
            self._json({"note": None})
            return
        self._json({"note": found[0], "body": notes.note_body(found[1])})

    def _sse(self, events: Iterator[dict[str, Any]]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            for event in events:
                self.wfile.write(f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            logger.info("Client closed the AI stream")
        finally:
            close = getattr(events, "close", None)
            if close:
                close()

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
    def _static(self, name: str) -> None:
        path = (WEB_DIR / name).resolve()
        if WEB_DIR not in path.parents or not path.is_file() or path.suffix not in STATIC_TYPES:
            self._error(404, "Not found")
            return
        self._send(200, path.read_bytes(), f"{STATIC_TYPES[path.suffix]}; charset=utf-8")

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
