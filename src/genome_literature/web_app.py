"""Web-based GUI for 3D Genome & Deep Learning Literature Hub.

Launch with: python run.py
Then open http://localhost:8686 in your browser.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any

from . import config
from .categorizer import categorize_papers, get_statistics, group_by_category
from .email_notifier import send_digest_email
from .fetcher import fetch_all_papers
from .readme_generator import generate_readme
from .storage import load_papers, merge_papers, save_papers
from .summarizer import generate_digest

logger = logging.getLogger(__name__)

# We use Python's built-in http.server to avoid extra dependencies
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import html as html_module

# Global state
_app_state: dict[str, Any] = {
    "status": "idle",       # idle | fetching | done | error
    "message": "",
    "papers": [],
    "last_result": None,
}


class GUIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the web GUI."""

    def log_message(self, format, *args):
        """Suppress default access logs."""
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "":
            self._serve_home()
        elif path == "/api/status":
            self._serve_json(_app_state)
        elif path == "/api/papers":
            self._serve_json(load_papers())
        elif path == "/api/stats":
            papers = load_papers()
            if papers:
                categorize_papers(papers)
                self._serve_json(get_statistics(papers))
            else:
                self._serve_json({"total_papers": 0})
        else:
            self._serve_404()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Read POST body
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length else ""

        if path == "/api/fetch":
            self._handle_fetch()
        elif path == "/api/update-readme":
            self._handle_update_readme()
        elif path == "/api/send-email":
            self._handle_send_email()
        elif path == "/api/run-pipeline":
            self._handle_run_pipeline()
        elif path == "/api/search":
            params = parse_qs(body) if body else parse_qs(urlparse(self.path).query)
            query = params.get("q", [""])[0]
            self._handle_search(query)
        elif path == "/api/export-csv":
            self._handle_export_csv()
        else:
            self._serve_404()

    # ------------------------------------------------------------------
    # API handlers
    # ------------------------------------------------------------------

    def _handle_fetch(self):
        if _app_state["status"] == "fetching":
            self._serve_json({"ok": False, "message": "Already fetching..."})
            return

        def do_fetch():
            _app_state["status"] = "fetching"
            _app_state["message"] = "Fetching papers from PubMed, bioRxiv, arXiv..."
            try:
                papers = fetch_all_papers()
                categorize_papers(papers)
                existing = load_papers()
                all_papers, new_papers = merge_papers(existing, papers)
                categorize_papers(all_papers)
                save_papers(all_papers)
                if new_papers:
                    save_papers(new_papers, config.NEW_PAPERS_JSON)
                _app_state["status"] = "done"
                _app_state["message"] = f"Done! Fetched {len(papers)} papers, {len(new_papers)} new. Total: {len(all_papers)}"
                _app_state["papers"] = all_papers
                _app_state["last_result"] = {
                    "fetched": len(papers),
                    "new": len(new_papers),
                    "total": len(all_papers),
                }
            except Exception as e:
                _app_state["status"] = "error"
                _app_state["message"] = f"Error: {e}"

        threading.Thread(target=do_fetch, daemon=True).start()
        self._serve_json({"ok": True, "message": "Fetching started..."})

    def _handle_update_readme(self):
        papers = load_papers()
        if not papers:
            self._serve_json({"ok": False, "message": "No papers in database. Please fetch first."})
            return
        categorize_papers(papers)
        content = generate_readme(papers)
        config.README_PATH.write_text(content, encoding="utf-8")
        self._serve_json({"ok": True, "message": f"README.md updated with {len(papers)} papers!"})

    def _handle_send_email(self):
        all_papers = load_papers()
        new_papers = load_papers(config.NEW_PAPERS_JSON)
        if not new_papers:
            self._serve_json({"ok": False, "message": "No new papers to report."})
            return
        categorize_papers(all_papers)
        categorize_papers(new_papers)
        digest = generate_digest(new_papers, all_papers)
        sent = send_digest_email(new_papers, digest)
        if sent:
            self._serve_json({"ok": True, "message": "Email sent successfully!"})
        else:
            self._serve_json({"ok": False, "message": "Failed to send email. Check SMTP configuration in .env file."})

    def _handle_run_pipeline(self):
        if _app_state["status"] == "fetching":
            self._serve_json({"ok": False, "message": "Pipeline already running..."})
            return

        def do_pipeline():
            _app_state["status"] = "fetching"
            _app_state["message"] = "Running full pipeline..."
            try:
                from .pipeline import run_pipeline
                result = run_pipeline(skip_email=False, skip_readme=False)
                _app_state["status"] = "done"
                _app_state["message"] = (
                    f"Pipeline done! Fetched {result.get('fetched_count', 0)} papers, "
                    f"{result.get('new_count', 0)} new. Total: {result.get('total_count', 0)}"
                )
                _app_state["last_result"] = result
            except Exception as e:
                _app_state["status"] = "error"
                _app_state["message"] = f"Error: {e}"

        threading.Thread(target=do_pipeline, daemon=True).start()
        self._serve_json({"ok": True, "message": "Pipeline started..."})

    def _handle_search(self, query: str):
        papers = load_papers()
        if not papers or not query:
            self._serve_json([])
            return
        terms = query.lower().split()
        results = []
        for p in papers:
            text = f"{p.get('title', '')} {p.get('abstract', '')} {' '.join(p.get('categories', []))}".lower()
            score = sum(1 for t in terms if t in text)
            if score > 0:
                results.append((score, p))
        results.sort(key=lambda x: x[0], reverse=True)
        self._serve_json([p for _, p in results[:30]])

    def _handle_export_csv(self):
        import csv
        import io
        papers = load_papers()
        if not papers:
            self._serve_error(400, "No papers to export")
            return
        output = io.StringIO()
        fields = ["title", "authors", "journal", "year", "date", "doi", "url", "source", "categories"]
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for p in papers:
            row = {**p}
            row["authors"] = "; ".join(p.get("authors", []))
            row["categories"] = "; ".join(p.get("categories", []))
            writer.writerow(row)
        csv_content = output.getvalue()

        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", "attachment; filename=papers_export.csv")
        self.end_headers()
        self.wfile.write(csv_content.encode("utf-8"))

    # ------------------------------------------------------------------
    # Response helpers
    # ------------------------------------------------------------------

    def _serve_home(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HOME_HTML.encode("utf-8"))

    def _serve_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"))

    def _serve_error(self, code, message):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": message}).encode("utf-8"))

    def _serve_404(self):
        self._serve_error(404, "Not found")


def start_server(port: int = 8686, open_browser: bool = True):
    """Start the web GUI server."""
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )

    server = HTTPServer(("0.0.0.0", port), GUIHandler)
    url = f"http://localhost:{port}"
    print(f"\n{'='*60}")
    print(f"  3D Genome & Deep Learning Literature Hub")
    print(f"  Web GUI running at: {url}")
    print(f"  Press Ctrl+C to stop")
    print(f"{'='*60}\n")

    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


# ------------------------------------------------------------------
# HTML template (embedded to avoid external file dependency)
# ------------------------------------------------------------------

HOME_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>3D Genome & Deep Learning Literature Hub</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }

.header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; text-align: center; }
.header h1 { font-size: 28px; font-weight: 700; margin-bottom: 8px; }
.header p { opacity: 0.85; font-size: 15px; }

.container { max-width: 1100px; margin: 0 auto; padding: 20px; }

.status-bar {
    background: #1e293b; border-radius: 10px; padding: 15px 20px;
    margin-bottom: 20px; display: flex; align-items: center; gap: 12px;
    border: 1px solid #334155;
}
.status-dot { width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }
.status-dot.idle { background: #94a3b8; }
.status-dot.fetching { background: #fbbf24; animation: pulse 1s infinite; }
.status-dot.done { background: #34d399; }
.status-dot.error { background: #f87171; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
.status-text { font-size: 14px; color: #cbd5e1; }

.actions {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 12px; margin-bottom: 24px;
}
.btn {
    padding: 14px 20px; border: none; border-radius: 10px; cursor: pointer;
    font-size: 15px; font-weight: 600; color: white; transition: all 0.2s;
    display: flex; align-items: center; gap: 8px; justify-content: center;
}
.btn:hover { transform: translateY(-2px); box-shadow: 0 4px 15px rgba(0,0,0,0.3); }
.btn:active { transform: translateY(0); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
.btn-fetch { background: linear-gradient(135deg, #667eea, #764ba2); }
.btn-readme { background: linear-gradient(135deg, #06b6d4, #0891b2); }
.btn-email { background: linear-gradient(135deg, #f59e0b, #d97706); }
.btn-pipeline { background: linear-gradient(135deg, #10b981, #059669); }
.btn-export { background: linear-gradient(135deg, #8b5cf6, #7c3aed); }
.btn-search-go { background: linear-gradient(135deg, #ec4899, #db2777); padding: 14px 24px; }

.search-box {
    display: flex; gap: 10px; margin-bottom: 24px;
}
.search-input {
    flex: 1; padding: 14px 18px; border-radius: 10px; border: 1px solid #334155;
    background: #1e293b; color: #e2e8f0; font-size: 15px; outline: none;
}
.search-input:focus { border-color: #667eea; }

.stats-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 12px; margin-bottom: 24px;
}
.stat-card {
    background: #1e293b; border-radius: 10px; padding: 20px; text-align: center;
    border: 1px solid #334155;
}
.stat-number { font-size: 36px; font-weight: 700; color: #667eea; }
.stat-label { font-size: 13px; color: #94a3b8; margin-top: 4px; }

.section { margin-bottom: 24px; }
.section h2 { font-size: 20px; margin-bottom: 12px; color: #f1f5f9; }

.paper-list { display: flex; flex-direction: column; gap: 10px; }
.paper-card {
    background: #1e293b; border-radius: 10px; padding: 16px 20px;
    border: 1px solid #334155; transition: border-color 0.2s;
}
.paper-card:hover { border-color: #667eea; }
.paper-title { font-size: 15px; font-weight: 600; color: #f1f5f9; margin-bottom: 6px; }
.paper-title a { color: #93c5fd; text-decoration: none; }
.paper-title a:hover { text-decoration: underline; }
.paper-meta { font-size: 13px; color: #94a3b8; margin-bottom: 4px; }
.paper-cats { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; }
.cat-tag {
    font-size: 11px; padding: 3px 8px; border-radius: 4px;
    background: #334155; color: #93c5fd;
}
.paper-abstract { font-size: 13px; color: #64748b; margin-top: 8px; line-height: 1.5; }

.empty-state { text-align: center; padding: 60px 20px; color: #64748b; }
.empty-state p { font-size: 16px; margin-bottom: 10px; }

.footer { text-align: center; padding: 30px; color: #475569; font-size: 13px; }
</style>
</head>
<body>

<div class="header">
    <h1>3D Genome & Deep Learning</h1>
    <p>Literature Hub — Auto-updating Research Tracker</p>
</div>

<div class="container">

    <!-- Status bar -->
    <div class="status-bar">
        <div class="status-dot" id="statusDot"></div>
        <span class="status-text" id="statusText">Ready</span>
    </div>

    <!-- Action buttons -->
    <div class="actions">
        <button class="btn btn-fetch" onclick="doAction('/api/fetch')" id="btnFetch">
            <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.66 0 3-4.03 3-9s-1.34-9-3-9m0 18c-1.66 0-3-4.03-3-9s1.34-9 3-9"/></svg>
            Fetch Papers
        </button>
        <button class="btn btn-readme" onclick="doAction('/api/update-readme')">
            <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg>
            Update README
        </button>
        <button class="btn btn-email" onclick="doAction('/api/send-email')">
            <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg>
            Send Email
        </button>
        <button class="btn btn-pipeline" onclick="doAction('/api/run-pipeline')" id="btnPipeline">
            <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
            One-Click Pipeline
        </button>
        <button class="btn btn-export" onclick="exportCSV()">
            <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
            Export CSV
        </button>
    </div>

    <!-- Search -->
    <div class="search-box">
        <input class="search-input" id="searchInput" type="text" placeholder="Search papers (e.g. Hi-C deep learning, TAD prediction, Akita...)" onkeydown="if(event.key==='Enter')doSearch()">
        <button class="btn btn-search-go" onclick="doSearch()">Search</button>
    </div>

    <!-- Stats -->
    <div class="stats-grid" id="statsGrid">
        <div class="stat-card"><div class="stat-number" id="statTotal">-</div><div class="stat-label">Total Papers</div></div>
        <div class="stat-card"><div class="stat-number" id="statSources">-</div><div class="stat-label">Sources</div></div>
        <div class="stat-card"><div class="stat-number" id="statCats">-</div><div class="stat-label">Categories</div></div>
        <div class="stat-card"><div class="stat-number" id="statYears">-</div><div class="stat-label">Year Span</div></div>
    </div>

    <!-- Papers -->
    <div class="section">
        <h2 id="papersTitle">Papers</h2>
        <div class="paper-list" id="paperList">
            <div class="empty-state">
                <p>No papers yet.</p>
                <p>Click <strong>"Fetch Papers"</strong> or <strong>"One-Click Pipeline"</strong> to get started!</p>
            </div>
        </div>
    </div>

</div>

<div class="footer">
    3D Genome & Deep Learning Literature Hub &mdash; Auto-generated by
    <a href="https://github.com/Yin-Shen/3DGenomeHub" style="color:#667eea;">3DGenomeHub</a>
</div>

<script>
// Poll status
let polling = null;

function updateStatus(status, message) {
    const dot = document.getElementById('statusDot');
    const text = document.getElementById('statusText');
    dot.className = 'status-dot ' + (status || 'idle');
    text.textContent = message || 'Ready';
}

function pollStatus() {
    fetch('/api/status').then(r => r.json()).then(data => {
        updateStatus(data.status, data.message);
        if (data.status === 'done' || data.status === 'error') {
            clearInterval(polling);
            polling = null;
            loadStats();
            loadPapers();
        }
    }).catch(() => {});
}

function doAction(endpoint) {
    fetch(endpoint, {method: 'POST'}).then(r => r.json()).then(data => {
        updateStatus('fetching', data.message);
        if (!polling) polling = setInterval(pollStatus, 2000);
    }).catch(e => updateStatus('error', 'Request failed: ' + e));
}

function doSearch() {
    const q = document.getElementById('searchInput').value.trim();
    if (!q) { loadPapers(); return; }
    fetch('/api/search', {method: 'POST', body: 'q=' + encodeURIComponent(q), headers: {'Content-Type': 'application/x-www-form-urlencoded'}})
        .then(r => r.json())
        .then(papers => {
            document.getElementById('papersTitle').textContent = `Search results for "${q}" (${papers.length})`;
            renderPapers(papers);
        });
}

function exportCSV() {
    window.location.href = '/api/export-csv';
}

function loadStats() {
    fetch('/api/stats').then(r => r.json()).then(data => {
        document.getElementById('statTotal').textContent = data.total_papers || 0;
        document.getElementById('statSources').textContent = Object.keys(data.by_source || {}).length;
        document.getElementById('statCats').textContent = Object.keys(data.by_category || {}).length;
        const years = Object.keys(data.by_year || {}).map(Number).sort();
        if (years.length >= 2) {
            document.getElementById('statYears').textContent = years[0] + '-' + years[years.length-1];
        } else if (years.length === 1) {
            document.getElementById('statYears').textContent = years[0];
        }
    });
}

function loadPapers() {
    fetch('/api/papers').then(r => r.json()).then(papers => {
        document.getElementById('papersTitle').textContent = `Papers (${papers.length})`;
        // Sort by date descending
        papers.sort((a, b) => (b.date || '').localeCompare(a.date || ''));
        renderPapers(papers.slice(0, 100));  // Show latest 100
    });
}

function renderPapers(papers) {
    const list = document.getElementById('paperList');
    if (!papers.length) {
        list.innerHTML = '<div class="empty-state"><p>No papers found.</p><p>Click <strong>"Fetch Papers"</strong> to get started!</p></div>';
        return;
    }
    list.innerHTML = papers.map(p => {
        const authors = (p.authors || []).length > 2
            ? p.authors[0] + ' et al.'
            : (p.authors || []).join(', ') || 'Unknown';
        const cats = (p.categories || []).map(c => `<span class="cat-tag">${esc(c)}</span>`).join('');
        const abstract = p.abstract ? `<div class="paper-abstract">${esc(p.abstract.substring(0, 250))}${p.abstract.length > 250 ? '...' : ''}</div>` : '';
        return `<div class="paper-card">
            <div class="paper-title"><a href="${esc(p.url || '#')}" target="_blank">${esc(p.title)}</a></div>
            <div class="paper-meta">${esc(authors)} &middot; ${esc(p.journal || '')} (${p.year || ''})</div>
            <div class="paper-cats">${cats}</div>
            ${abstract}
        </div>`;
    }).join('');
}

function esc(s) {
    if (!s) return '';
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}

// Init
loadStats();
loadPapers();
</script>
</body>
</html>
"""
