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

from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

_app_state: dict[str, Any] = {
    "status": "idle",
    "message": "",
    "papers": [],
    "last_result": None,
}


class GUIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
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
                stats = get_statistics(papers)
                grouped = group_by_category(papers)
                cat_counts = {k: len(v) for k, v in grouped.items()}
                stats["category_counts"] = cat_counts
                # year list
                stats["years"] = sorted(stats.get("by_year", {}).keys(), reverse=True)
                # source list
                stats["sources"] = sorted(stats.get("by_source", {}).keys())
                # category list
                stats["categories"] = list(cat_counts.keys())
                self._serve_json(stats)
            else:
                self._serve_json({"total_papers": 0, "categories": [], "years": [], "sources": []})
        elif path == "/api/digest":
            papers = load_papers()
            new_papers = load_papers(config.NEW_PAPERS_JSON)
            if papers:
                categorize_papers(papers)
                if new_papers:
                    categorize_papers(new_papers)
                digest = generate_digest(new_papers or [], papers)
                self._serve_json(digest)
            else:
                self._serve_json({"summary_text": "No papers yet.", "statistics": {}})
        elif path == "/api/analysis":
            papers = load_papers()
            if papers:
                categorize_papers(papers)
                from .analyzer import analyze_papers
                analysis = analyze_papers(papers)
                self._serve_json(analysis)
            else:
                self._serve_json({"research_summary": "No papers yet.", "dl_method_distribution": {}})
        elif path == "/api/export-csv":
            self._handle_export_csv()
        else:
            self._serve_404()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
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
        else:
            self._serve_404()

    def _handle_fetch(self):
        if _app_state["status"] == "fetching":
            self._serve_json({"ok": False, "message": "Already fetching..."})
            return
        def do_fetch():
            _app_state["status"] = "fetching"
            _app_state["message"] = "Fetching from PubMed, bioRxiv, arXiv, Semantic Scholar, Europe PMC, CrossRef..."
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
            except Exception as e:
                _app_state["status"] = "error"
                _app_state["message"] = f"Error: {e}"
        threading.Thread(target=do_fetch, daemon=True).start()
        self._serve_json({"ok": True, "message": "Fetching started..."})

    def _handle_update_readme(self):
        papers = load_papers()
        if not papers:
            self._serve_json({"ok": False, "message": "No papers in database."})
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
            self._serve_json({"ok": False, "message": "Failed to send. Check .env SMTP config."})

    def _handle_run_pipeline(self):
        if _app_state["status"] == "fetching":
            self._serve_json({"ok": False, "message": "Already running..."})
            return
        def do_pipeline():
            _app_state["status"] = "fetching"
            _app_state["message"] = "Running full pipeline (6 databases)..."
            try:
                from .pipeline import run_pipeline
                result = run_pipeline(skip_email=False, skip_readme=False)
                _app_state["status"] = "done"
                _app_state["message"] = (
                    f"Pipeline done! Fetched {result.get('fetched_count', 0)}, "
                    f"{result.get('new_count', 0)} new. Total: {result.get('total_count', 0)}"
                )
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
        self._serve_json([p for _, p in results[:50]])

    def _handle_export_csv(self):
        import csv, io
        papers = load_papers()
        if not papers:
            self._serve_error(400, "No papers")
            return
        output = io.StringIO()
        fields = ["title", "authors", "journal", "year", "date", "doi", "url", "source", "categories", "abstract"]
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for p in papers:
            row = {**p}
            row["authors"] = "; ".join(p.get("authors", []))
            row["categories"] = "; ".join(p.get("categories", []))
            writer.writerow(row)
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", "attachment; filename=3DGenomeHub_papers.csv")
        self.end_headers()
        self.wfile.write(output.getvalue().encode("utf-8"))

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
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S", stream=sys.stderr)
    server = HTTPServer(("0.0.0.0", port), GUIHandler)
    url = f"http://localhost:{port}"
    print(f"\n{'='*60}")
    print(f"  3D Genome & Deep Learning Literature Hub")
    print(f"  Web GUI: {url}")
    print(f"  Press Ctrl+C to stop")
    print(f"{'='*60}\n")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


HOME_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>3D Genome & Deep Learning Literature Hub</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0b0f1a;color:#e2e8f0;min-height:100vh}
a{color:#93c5fd;text-decoration:none}
a:hover{text-decoration:underline}

.header{background:linear-gradient(135deg,#1e3a5f 0%,#4c1d95 50%,#831843 100%);padding:28px 20px;text-align:center}
.header h1{font-size:26px;font-weight:700}
.header p{opacity:0.8;font-size:14px;margin-top:6px}

.container{max-width:1300px;margin:0 auto;padding:16px}

.status-bar{background:#131a2e;border-radius:8px;padding:12px 16px;margin-bottom:14px;display:flex;align-items:center;gap:10px;border:1px solid #1e293b}
.status-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0}
.status-dot.idle{background:#94a3b8}.status-dot.fetching{background:#fbbf24;animation:pulse 1s infinite}.status-dot.done{background:#34d399}.status-dot.error{background:#f87171}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.3}}
.status-text{font-size:13px;color:#94a3b8}

.actions{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px}
.btn{padding:10px 16px;border:none;border-radius:8px;cursor:pointer;font-size:13px;font-weight:600;color:white;transition:all 0.15s;display:flex;align-items:center;gap:6px}
.btn:hover{transform:translateY(-1px);box-shadow:0 3px 12px rgba(0,0,0,0.3)}
.btn:disabled{opacity:0.4;cursor:not-allowed;transform:none}
.btn-fetch{background:#4f46e5}.btn-readme{background:#0891b2}.btn-email{background:#d97706}.btn-pipeline{background:#059669}.btn-export{background:#7c3aed}

.main-grid{display:grid;grid-template-columns:280px 1fr;gap:14px}
@media(max-width:900px){.main-grid{grid-template-columns:1fr}}

/* Sidebar */
.sidebar{display:flex;flex-direction:column;gap:12px}
.panel{background:#131a2e;border-radius:8px;padding:14px;border:1px solid #1e293b}
.panel h3{font-size:14px;font-weight:600;color:#f1f5f9;margin-bottom:10px;display:flex;align-items:center;gap:6px}

.stats-mini{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.stat-mini{text-align:center;padding:10px 6px;background:#0b0f1a;border-radius:6px}
.stat-mini .num{font-size:24px;font-weight:700;color:#818cf8}
.stat-mini .lbl{font-size:11px;color:#64748b;margin-top:2px}

.filter-group{margin-bottom:10px}
.filter-group label{font-size:12px;color:#94a3b8;display:block;margin-bottom:4px;font-weight:500}
.filter-group select,.filter-group input{width:100%;padding:7px 10px;border-radius:6px;border:1px solid #334155;background:#0b0f1a;color:#e2e8f0;font-size:13px;outline:none}
.filter-group select:focus,.filter-group input:focus{border-color:#818cf8}

.cat-list{max-height:320px;overflow-y:auto;font-size:12px}
.cat-list::-webkit-scrollbar{width:4px}
.cat-list::-webkit-scrollbar-thumb{background:#334155;border-radius:2px}
.cat-item{display:flex;justify-content:space-between;padding:5px 8px;border-radius:4px;cursor:pointer;transition:background 0.1s}
.cat-item:hover,.cat-item.active{background:#1e293b}
.cat-item .name{color:#cbd5e1;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cat-item .cnt{color:#818cf8;font-weight:600;margin-left:6px;flex-shrink:0}

.digest-box{font-size:12px;color:#94a3b8;line-height:1.6;white-space:pre-line;max-height:200px;overflow-y:auto}

/* Content */
.content{display:flex;flex-direction:column;gap:12px}

.search-bar{display:flex;gap:8px}
.search-input{flex:1;padding:10px 14px;border-radius:8px;border:1px solid #334155;background:#131a2e;color:#e2e8f0;font-size:14px;outline:none}
.search-input:focus{border-color:#818cf8}
.btn-search{background:linear-gradient(135deg,#ec4899,#8b5cf6);padding:10px 20px;border-radius:8px;border:none;color:white;font-weight:600;cursor:pointer;font-size:14px}

.toolbar{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}
.toolbar .info{font-size:13px;color:#94a3b8}
.sort-sel{padding:6px 10px;border-radius:6px;border:1px solid #334155;background:#131a2e;color:#e2e8f0;font-size:12px;outline:none}

.paper-list{display:flex;flex-direction:column;gap:8px}
.paper-card{background:#131a2e;border-radius:8px;padding:14px 16px;border:1px solid #1e293b;transition:border-color 0.15s}
.paper-card:hover{border-color:#4f46e5}
.paper-title{font-size:14px;font-weight:600;line-height:1.4;margin-bottom:5px}
.paper-meta{font-size:12px;color:#64748b;margin-bottom:5px}
.paper-meta .source-tag{display:inline-block;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:600;margin-left:6px}
.src-pubmed{background:#164e63;color:#67e8f9}.src-biorxiv{background:#3f3f14;color:#fde047}.src-arxiv{background:#4a1942;color:#f0abfc}
.src-semantic_scholar{background:#1e3a2f;color:#6ee7b7}.src-europepmc{background:#1e293b;color:#93c5fd}.src-crossref{background:#3b1e0f;color:#fdba74}
.paper-cats{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:5px}
.cat-tag{font-size:10px;padding:2px 7px;border-radius:3px;background:#1e293b;color:#a5b4fc;border:1px solid #334155}
.paper-abstract{font-size:12px;color:#64748b;line-height:1.5;cursor:pointer}
.paper-abstract.expanded{color:#94a3b8;max-height:none!important}
.paper-links{margin-top:6px;font-size:12px;display:flex;gap:10px}
.paper-links a{color:#818cf8}

.pagination{display:flex;justify-content:center;gap:6px;margin-top:10px}
.page-btn{padding:6px 12px;border-radius:6px;border:1px solid #334155;background:#131a2e;color:#e2e8f0;cursor:pointer;font-size:12px}
.page-btn:hover,.page-btn.active{background:#4f46e5;border-color:#4f46e5}
.page-btn:disabled{opacity:0.3;cursor:not-allowed}

.empty-state{text-align:center;padding:50px 20px;color:#475569}
.footer{text-align:center;padding:20px;color:#334155;font-size:12px;margin-top:10px}
</style>
</head>
<body>

<div class="header">
    <h1>3D Genome & Deep Learning Literature Hub</h1>
    <p>Comprehensive Auto-updating Research Tracker | 6 Databases | 19 Categories</p>
</div>

<div class="container">
    <div class="status-bar">
        <div class="status-dot" id="statusDot"></div>
        <span class="status-text" id="statusText">Ready</span>
    </div>

    <div class="actions">
        <button class="btn btn-fetch" onclick="doAction('/api/fetch')">Fetch Papers (6 DBs)</button>
        <button class="btn btn-pipeline" onclick="doAction('/api/run-pipeline')">One-Click Full Pipeline</button>
        <button class="btn btn-readme" onclick="doAction('/api/update-readme')">Update README</button>
        <button class="btn btn-email" onclick="doAction('/api/send-email')">Send Email Digest</button>
        <button class="btn btn-export" onclick="location.href='/api/export-csv'">Export CSV</button>
        <button class="btn" style="background:#b91c1c" onclick="showAnalysis()">AI Analysis</button>
    </div>

    <!-- AI Analysis Modal -->
    <div id="analysisModal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.8);z-index:999;overflow-y:auto">
      <div style="max-width:1000px;margin:30px auto;background:#131a2e;border-radius:12px;padding:24px;border:1px solid #334155;position:relative">
        <button onclick="document.getElementById('analysisModal').style.display='none'" style="position:absolute;top:12px;right:16px;background:none;border:none;color:#94a3b8;font-size:24px;cursor:pointer">&times;</button>
        <h2 style="font-size:20px;color:#f1f5f9;margin-bottom:16px">AI Research Analysis: 3D Genome × Deep Learning</h2>
        <div id="analysisContent" style="color:#cbd5e1">
          <p style="color:#94a3b8">Loading analysis...</p>
        </div>
      </div>
    </div>

    <div class="main-grid">
        <!-- Sidebar -->
        <div class="sidebar">
            <div class="panel">
                <h3>Statistics</h3>
                <div class="stats-mini">
                    <div class="stat-mini"><div class="num" id="sTotal">-</div><div class="lbl">Papers</div></div>
                    <div class="stat-mini"><div class="num" id="sSources">-</div><div class="lbl">Sources</div></div>
                    <div class="stat-mini"><div class="num" id="sCats">-</div><div class="lbl">Categories</div></div>
                    <div class="stat-mini"><div class="num" id="sYears">-</div><div class="lbl">Year Span</div></div>
                </div>
            </div>

            <div class="panel">
                <h3>Filters</h3>
                <div class="filter-group">
                    <label>Source</label>
                    <select id="filterSource" onchange="applyFilters()"><option value="">All Sources</option></select>
                </div>
                <div class="filter-group">
                    <label>Year Range</label>
                    <div style="display:flex;gap:4px">
                        <select id="filterYearFrom" onchange="applyFilters()"><option value="">From</option></select>
                        <select id="filterYearTo" onchange="applyFilters()"><option value="">To</option></select>
                    </div>
                </div>
                <div class="filter-group">
                    <label>Sort By</label>
                    <select id="sortBy" onchange="applyFilters()">
                        <option value="date_desc">Newest First</option>
                        <option value="date_asc">Oldest First</option>
                        <option value="title_asc">Title A-Z</option>
                        <option value="relevance" id="sortRelevance" style="display:none">Relevance</option>
                    </select>
                </div>
            </div>

            <div class="panel">
                <h3>Categories</h3>
                <div class="cat-list" id="catList"></div>
            </div>

            <div class="panel">
                <h3>DL Methods</h3>
                <div class="cat-list" id="dlMethodList" style="max-height:200px"><span style="color:#64748b;font-size:12px">Click "AI Analysis"</span></div>
            </div>

            <div class="panel">
                <h3>Hot Topics</h3>
                <div id="hotTopics" style="font-size:12px;color:#94a3b8;max-height:200px;overflow-y:auto"><span style="color:#64748b">Click "AI Analysis"</span></div>
            </div>

            <div class="panel">
                <h3>Latest Digest</h3>
                <div class="digest-box" id="digestBox">Loading...</div>
            </div>
        </div>

        <!-- Content -->
        <div class="content">
            <div class="search-bar">
                <input class="search-input" id="searchInput" type="text" placeholder="Search papers by title, abstract, author, category..." onkeydown="if(event.key==='Enter')doSearch()">
                <button class="btn-search" onclick="doSearch()">Search</button>
            </div>

            <div class="toolbar">
                <span class="info" id="resultInfo">Loading papers...</span>
            </div>

            <div class="paper-list" id="paperList">
                <div class="empty-state"><p>Loading...</p></div>
            </div>

            <div class="pagination" id="pagination"></div>
        </div>
    </div>
</div>

<div class="footer">3D Genome & Deep Learning Literature Hub &mdash; <a href="https://github.com/Yin-Shen/3DGenomeHub">GitHub</a></div>

<script>
let ALL_PAPERS = [];
let FILTERED = [];
let PAGE = 1;
const PER_PAGE = 25;
let polling = null;
let activeCategory = "";
let searchMode = false;

function updateStatus(s, m) {
    document.getElementById('statusDot').className = 'status-dot ' + (s||'idle');
    document.getElementById('statusText').textContent = m || 'Ready';
}

function pollStatus() {
    fetch('/api/status').then(r=>r.json()).then(d=>{
        updateStatus(d.status, d.message);
        if(d.status==='done'||d.status==='error'){clearInterval(polling);polling=null;loadAll();}
    }).catch(()=>{});
}

function doAction(ep) {
    fetch(ep,{method:'POST'}).then(r=>r.json()).then(d=>{
        updateStatus('fetching', d.message);
        if(!polling) polling = setInterval(pollStatus, 2000);
    });
}

function doSearch() {
    const q = document.getElementById('searchInput').value.trim();
    if(!q){searchMode=false;document.getElementById('sortRelevance').style.display='none';applyFilters();return;}
    searchMode = true;
    document.getElementById('sortRelevance').style.display='';
    document.getElementById('sortBy').value='relevance';
    fetch('/api/search',{method:'POST',body:'q='+encodeURIComponent(q),headers:{'Content-Type':'application/x-www-form-urlencoded'}})
        .then(r=>r.json()).then(papers=>{
            FILTERED = papers;
            PAGE = 1;
            renderResults(`Search: "${q}" (${papers.length} results)`);
        });
}

function applyFilters() {
    if(searchMode && document.getElementById('sortBy').value==='relevance') { renderPaginated(); return; }
    searchMode = false;
    const src = document.getElementById('filterSource').value;
    const yFrom = parseInt(document.getElementById('filterYearFrom').value) || 0;
    const yTo = parseInt(document.getElementById('filterYearTo').value) || 9999;
    const sort = document.getElementById('sortBy').value;

    FILTERED = ALL_PAPERS.filter(p => {
        if(src && p.source !== src) return false;
        if(p.year < yFrom || p.year > yTo) return false;
        if(activeCategory && !(p.categories||[]).includes(activeCategory)) return false;
        return true;
    });

    if(sort==='date_desc') FILTERED.sort((a,b)=>(b.date||'').localeCompare(a.date||''));
    else if(sort==='date_asc') FILTERED.sort((a,b)=>(a.date||'').localeCompare(b.date||''));
    else if(sort==='title_asc') FILTERED.sort((a,b)=>(a.title||'').localeCompare(b.title||''));

    PAGE = 1;
    const label = activeCategory ? `${activeCategory} (${FILTERED.length})` : `All Papers (${FILTERED.length})`;
    renderResults(label);
}

function renderResults(label) {
    document.getElementById('resultInfo').textContent = label;
    renderPaginated();
}

function renderPaginated() {
    const total = FILTERED.length;
    const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));
    if(PAGE > totalPages) PAGE = totalPages;
    const start = (PAGE-1)*PER_PAGE;
    const slice = FILTERED.slice(start, start+PER_PAGE);
    renderPapers(slice);
    renderPagination(totalPages);
}

function renderPapers(papers) {
    const list = document.getElementById('paperList');
    if(!papers.length){list.innerHTML='<div class="empty-state"><p>No papers found. Click "Fetch Papers" to get started!</p></div>';return;}
    list.innerHTML = papers.map(p => {
        const authors = (p.authors||[]).length>2 ? p.authors[0]+' et al.' : (p.authors||[]).join(', ')||'Unknown';
        const cats = (p.categories||[]).map(c=>`<span class="cat-tag">${esc(c)}</span>`).join('');
        const srcClass = 'src-'+(p.source||'').replace(/ /g,'_');
        const abs = p.abstract||'';
        const absShort = abs.length>300 ? abs.substring(0,300)+'...' : abs;
        const links = [];
        if(p.url) links.push(`<a href="${esc(p.url)}" target="_blank">Paper</a>`);
        if(p.doi) links.push(`<a href="https://doi.org/${esc(p.doi)}" target="_blank">DOI</a>`);
        if(p.doi) links.push(`<a href="https://scholar.google.com/scholar?q=${encodeURIComponent(p.title)}" target="_blank">Google Scholar</a>`);
        return `<div class="paper-card">
            <div class="paper-title"><a href="${esc(p.url||'#')}" target="_blank">${esc(p.title)}</a></div>
            <div class="paper-meta">${esc(authors)} · ${esc(p.journal||'')} (${p.year||''}) <span class="source-tag ${srcClass}">${esc(p.source||'')}</span></div>
            <div class="paper-cats">${cats}</div>
            ${abs ? `<div class="paper-abstract" onclick="this.classList.toggle('expanded');this.textContent=this.classList.contains('expanded')?'${esc(abs).replace(/'/g,"\\'")}':'${esc(absShort).replace(/'/g,"\\'")}';" style="max-height:60px;overflow:hidden">${esc(absShort)}</div>` : ''}
            <div class="paper-links">${links.join(' · ')}</div>
        </div>`;
    }).join('');
}

function renderPagination(totalPages) {
    const el = document.getElementById('pagination');
    if(totalPages<=1){el.innerHTML='';return;}
    let html = `<button class="page-btn" onclick="goPage(${PAGE-1})" ${PAGE<=1?'disabled':''}>Prev</button>`;
    const range = 2;
    for(let i=1;i<=totalPages;i++){
        if(i===1||i===totalPages||Math.abs(i-PAGE)<=range){
            html+=`<button class="page-btn${i===PAGE?' active':''}" onclick="goPage(${i})">${i}</button>`;
        } else if(i===PAGE-range-1||i===PAGE+range+1){
            html+=`<button class="page-btn" disabled>...</button>`;
        }
    }
    html+=`<button class="page-btn" onclick="goPage(${PAGE+1})" ${PAGE>=totalPages?'disabled':''}>Next</button>`;
    el.innerHTML=html;
}
function goPage(p){PAGE=p;renderPaginated();window.scrollTo({top:300,behavior:'smooth'});}

function selectCategory(cat) {
    activeCategory = (activeCategory===cat) ? "" : cat;
    document.querySelectorAll('.cat-item').forEach(el=>{
        el.classList.toggle('active', el.dataset.cat===activeCategory);
    });
    searchMode=false;
    document.getElementById('searchInput').value='';
    applyFilters();
}

function loadAll() {
    fetch('/api/papers').then(r=>r.json()).then(papers=>{
        ALL_PAPERS = papers;
        FILTERED = [...papers];
        FILTERED.sort((a,b)=>(b.date||'').localeCompare(a.date||''));
        loadStats();
        loadDigest();
        applyFilters();
    });
}

function loadStats() {
    fetch('/api/stats').then(r=>r.json()).then(s=>{
        document.getElementById('sTotal').textContent = s.total_papers||0;
        document.getElementById('sSources').textContent = Object.keys(s.by_source||{}).length;
        document.getElementById('sCats').textContent = (s.categories||[]).length;
        const years = (s.years||[]);
        document.getElementById('sYears').textContent = years.length>=2 ? years[years.length-1]+'-'+years[0] : (years[0]||'-');

        // Populate filters
        const srcSel = document.getElementById('filterSource');
        srcSel.innerHTML = '<option value="">All Sources</option>';
        (s.sources||[]).forEach(src=>{srcSel.innerHTML+=`<option value="${src}">${src} (${(s.by_source||{})[src]||0})</option>`;});

        const yFromSel = document.getElementById('filterYearFrom');
        const yToSel = document.getElementById('filterYearTo');
        yFromSel.innerHTML='<option value="">From</option>';
        yToSel.innerHTML='<option value="">To</option>';
        years.forEach(y=>{yFromSel.innerHTML+=`<option value="${y}">${y}</option>`;yToSel.innerHTML+=`<option value="${y}">${y}</option>`;});

        // Category list
        const catList = document.getElementById('catList');
        const cc = s.category_counts||{};
        catList.innerHTML = Object.entries(cc).map(([cat,cnt])=>
            `<div class="cat-item" data-cat="${esc(cat)}" onclick="selectCategory('${esc(cat).replace(/'/g,"\\'")}')"><span class="name" title="${esc(cat)}">${esc(cat)}</span><span class="cnt">${cnt}</span></div>`
        ).join('');
    });
}

function loadDigest() {
    fetch('/api/digest').then(r=>r.json()).then(d=>{
        document.getElementById('digestBox').textContent = d.summary_text || 'No digest available.';
    }).catch(()=>{});
}

function showAnalysis() {
    const modal = document.getElementById('analysisModal');
    modal.style.display = 'block';
    document.getElementById('analysisContent').innerHTML = '<p style="color:#fbbf24">Analyzing papers... This may take a moment.</p>';
    fetch('/api/analysis').then(r=>r.json()).then(a=>{
        let html = '';

        // Summary
        html += `<div style="background:#0b0f1a;border-radius:8px;padding:16px;margin-bottom:16px;white-space:pre-line;font-size:13px;line-height:1.6;font-family:monospace;color:#a5b4fc">${esc(a.research_summary||'')}</div>`;

        // DL stats
        html += `<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:16px">`;
        html += `<div style="background:#1e1b4b;border-radius:8px;padding:14px;text-align:center"><div style="font-size:28px;font-weight:700;color:#818cf8">${a.dl_paper_count||0}</div><div style="font-size:12px;color:#94a3b8">DL Papers</div></div>`;
        html += `<div style="background:#1e1b4b;border-radius:8px;padding:14px;text-align:center"><div style="font-size:28px;font-weight:700;color:#34d399">${a.dl_ratio||0}%</div><div style="font-size:12px;color:#94a3b8">DL Ratio</div></div>`;
        html += `<div style="background:#1e1b4b;border-radius:8px;padding:14px;text-align:center"><div style="font-size:28px;font-weight:700;color:#fbbf24">${Object.keys(a.dl_method_distribution||{}).length}</div><div style="font-size:12px;color:#94a3b8">DL Methods</div></div>`;
        html += `</div>`;

        // DL Method distribution bar chart
        const methods = a.dl_method_distribution || {};
        if(Object.keys(methods).length) {
            html += `<h3 style="font-size:15px;margin-bottom:10px;color:#f1f5f9">Deep Learning Architecture Distribution</h3>`;
            const maxVal = Math.max(...Object.values(methods));
            html += `<div style="margin-bottom:16px">`;
            for(const [m, c] of Object.entries(methods)) {
                const pct = Math.round(c/maxVal*100);
                html += `<div style="display:flex;align-items:center;margin-bottom:4px;font-size:12px">
                    <span style="width:160px;color:#cbd5e1;flex-shrink:0">${esc(m)}</span>
                    <div style="flex:1;background:#1e293b;border-radius:3px;height:18px;margin:0 8px">
                        <div style="width:${pct}%;background:linear-gradient(90deg,#818cf8,#6366f1);height:100%;border-radius:3px;min-width:2px"></div>
                    </div>
                    <span style="color:#818cf8;width:30px;text-align:right">${c}</span>
                </div>`;
            }
            html += `</div>`;
        }

        // Tool mentions
        const tools = a.tool_mentions || {};
        if(Object.keys(tools).length) {
            html += `<h3 style="font-size:15px;margin-bottom:10px;color:#f1f5f9">Most Referenced Tools & Models</h3>`;
            html += `<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:16px">`;
            for(const [t, c] of Object.entries(tools)) {
                const size = Math.min(Math.max(12, 10+c*2), 24);
                html += `<span style="background:#1e293b;border:1px solid #334155;border-radius:6px;padding:4px 10px;font-size:${size}px;color:#93c5fd">${esc(t)} <sup style="color:#818cf8">${c}</sup></span>`;
            }
            html += `</div>`;
        }

        // Hot topics
        const hot = a.hot_topics || [];
        if(hot.length) {
            html += `<h3 style="font-size:15px;margin-bottom:10px;color:#f1f5f9">Hot Research Directions (Recent)</h3>`;
            html += `<div style="margin-bottom:16px">`;
            hot.forEach((h,i) => {
                html += `<div style="display:flex;align-items:center;padding:6px 10px;background:${i%2?'transparent':'#0b0f1a'};border-radius:4px;font-size:13px">
                    <span style="color:#fbbf24;margin-right:8px">🔥</span>
                    <span style="color:#e2e8f0;flex:1">${esc(h.topic)}</span>
                    <span style="color:#818cf8;font-weight:600">${h.count}</span>
                </div>`;
            });
            html += `</div>`;
        }

        // Category insights
        const insights = a.category_insights || {};
        if(Object.keys(insights).length) {
            html += `<h3 style="font-size:15px;margin-bottom:10px;color:#f1f5f9">Category Insights</h3>`;
            html += `<table style="width:100%;font-size:12px;border-collapse:collapse;margin-bottom:16px">`;
            html += `<tr style="border-bottom:1px solid #334155"><th style="text-align:left;padding:6px;color:#94a3b8">Category</th><th style="text-align:left;padding:6px;color:#94a3b8">Status</th></tr>`;
            for(const [cat, info] of Object.entries(insights)) {
                const color = info.includes('rapidly') ? '#34d399' : info.includes('actively') ? '#fbbf24' : '#94a3b8';
                html += `<tr style="border-bottom:1px solid #1e293b"><td style="padding:6px;color:#cbd5e1">${esc(cat)}</td><td style="padding:6px;color:${color}">${esc(info)}</td></tr>`;
            }
            html += `</table>`;
        }

        // Trend analysis
        const trend = a.trend_analysis || {};
        const trendYears = Object.keys(trend).sort().reverse().slice(0, 5);
        if(trendYears.length) {
            html += `<h3 style="font-size:15px;margin-bottom:10px;color:#f1f5f9">Year-by-Year Trend</h3>`;
            html += `<table style="width:100%;font-size:12px;border-collapse:collapse">`;
            html += `<tr style="border-bottom:1px solid #334155"><th style="padding:6px;color:#94a3b8">Year</th><th style="padding:6px;color:#94a3b8">Papers</th><th style="padding:6px;color:#94a3b8;text-align:left">Top Methods</th></tr>`;
            trendYears.forEach(y => {
                const t = trend[y];
                const methods = Object.entries(t.top_methods||{}).map(([m,c])=>`${m}(${c})`).join(', ');
                html += `<tr style="border-bottom:1px solid #1e293b"><td style="padding:6px;color:#818cf8;text-align:center">${y}</td><td style="padding:6px;color:#e2e8f0;text-align:center">${t.total}</td><td style="padding:6px;color:#94a3b8">${methods}</td></tr>`;
            });
            html += `</table>`;
        }

        document.getElementById('analysisContent').innerHTML = html;

        // Also update sidebar
        updateSidebarAnalysis(a);
    }).catch(e=>{
        document.getElementById('analysisContent').innerHTML = `<p style="color:#f87171">Analysis failed: ${e}</p>`;
    });
}

function updateSidebarAnalysis(a) {
    // DL Methods sidebar
    const methods = a.dl_method_distribution || {};
    const mlEl = document.getElementById('dlMethodList');
    if(Object.keys(methods).length) {
        mlEl.innerHTML = Object.entries(methods).map(([m,c])=>
            `<div class="cat-item"><span class="name">${esc(m)}</span><span class="cnt">${c}</span></div>`
        ).join('');
    }
    // Hot topics sidebar
    const hot = a.hot_topics || [];
    const htEl = document.getElementById('hotTopics');
    if(hot.length) {
        htEl.innerHTML = hot.map(h=>
            `<div style="padding:3px 0;border-bottom:1px solid #1e293b"><span style="color:#fbbf24;margin-right:4px">•</span>${esc(h.topic)} <span style="color:#818cf8">(${h.count})</span></div>`
        ).join('');
    }
}

function esc(s){if(!s)return'';const d=document.createElement('div');d.textContent=s;return d.innerHTML;}

loadAll();
</script>
</body>
</html>
"""
