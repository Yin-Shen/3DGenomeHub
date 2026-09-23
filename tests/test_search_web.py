from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from genome_literature import web_app
from genome_literature.records import new_record
from genome_literature.relevance import filter_relevant
from genome_literature.categorizer import categorize_papers
from genome_literature.search import search_papers, to_bibtex, to_csv
from genome_literature.storage import save_papers


def _papers():
    raw = [
        new_record("pubmed", title="Transformer model predicts Hi-C contact maps", doi="10.1/a",
                   abstract="A transformer with attention mechanism predicts chromatin contacts.", authors=["Doe J"],
                   journal="Cell", date="2025-01-02", citations=10),
        new_record("arxiv", title="Loop extrusion polymer simulations of TADs", arxiv_id="2501.1",
                   abstract="Polymer model of cohesin loop extrusion reproduces Hi-C.", authors=["Roe R"],
                   journal="arXiv (preprint)", date="2024-05-01"),
    ]
    kept, _ = filter_relevant(raw)
    return categorize_papers(kept)


def test_search_and_semantics():
    papers = _papers()
    assert [p["doi"] for p in search_papers(papers, "transformer hi-c")] == ["10.1/a"]
    assert search_papers(papers, '"loop extrusion" cohesin')[0]["arxiv_id"] == "2501.1"
    assert search_papers(papers, "transformer cohesin") == []
    assert search_papers(papers, "") == []


def test_exports():
    papers = _papers()
    csv_text = to_csv(papers)
    assert csv_text.splitlines()[0].startswith("id,title,authors")
    bib = to_bibtex(papers)
    assert "@article{doe2025transformer," in bib and "@misc{roe2024loop," in bib


@pytest.fixture
def server(tmp_project):
    save_papers(_papers())
    web_app._cache.update(mtime=None, papers=[])
    srv = web_app.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.status, r.headers.get("Content-Type"), r.read().decode("utf-8")


def test_web_endpoints(server):
    status, ctype, body = _get(server + "/")
    assert status == 200 and "3D Genome" in body and "text/html" in ctype
    _, _, body = _get(server + "/api/papers")
    assert len(json.loads(body)) == 2
    _, _, body = _get(server + "/api/stats")
    stats = json.loads(body)
    assert stats["total_papers"] == 2 and stats["ml_papers"] == 1
    _, _, body = _get(server + "/api/search?q=transformer")
    assert json.loads(body)[0]["doi"] == "10.1/a"
    _, _, body = _get(server + "/api/analysis")
    assert json.loads(body)["dl_paper_count"] == 1
    _, ctype, body = _get(server + "/api/export?format=bib")
    assert "bibtex" in ctype and "@article" in body


def test_post_requires_custom_header(server):
    req = urllib.request.Request(server + "/api/send-email", method="POST", data=b"")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=10)
    assert exc.value.code == 403
    req = urllib.request.Request(server + "/api/update-readme", method="POST", data=b"",
                                 headers={"X-Requested-With": "3DGenomeHub"})
    with urllib.request.urlopen(req, timeout=10) as r:
        assert json.loads(r.read())["ok"] is True
    deadline = time.time() + 10
    while time.time() < deadline:
        _, _, body = _get(server + "/api/status")
        if json.loads(body)["status"] != "running":
            break
        time.sleep(0.05)
    status = json.loads(body)
    assert status["status"] == "done", status
    assert "README.md and" in status["message"]


def test_email_html_is_escaped_and_capped(tmp_project, monkeypatch):
    from genome_literature import config
    from genome_literature.email_notifier import render_email_html
    from genome_literature.summarizer import generate_digest

    papers = _papers()
    papers[0]["title"] = "<script>alert(1)</script> Hi-C transformer"
    monkeypatch.setattr(config, "EMAIL_MAX_PAPERS", 1)
    html = render_email_html(papers, generate_digest(papers, papers))
    assert "<script>alert" not in html and "&lt;script&gt;" in html
    assert "1 more papers" in html
    monkeypatch.setattr(config, "TEMPLATE_DIR", tmp_project / "missing")
    fallback = render_email_html(papers, generate_digest(papers, papers))
    assert "&lt;script&gt;" in fallback
