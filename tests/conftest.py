from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from genome_literature import config  # noqa: E402
from genome_literature.net import HttpClient  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fixture_json(name: str):
    return json.loads(fixture_bytes(name))


def api_router(request: httpx.Request) -> httpx.Response:
    host, path = request.url.host, request.url.path
    if host == "eutils.ncbi.nlm.nih.gov" and path.endswith("esearch.fcgi"):
        return httpx.Response(200, content=fixture_bytes("esearch.json"))
    if host == "eutils.ncbi.nlm.nih.gov" and path.endswith("efetch.fcgi"):
        return httpx.Response(200, content=fixture_bytes("pubmed_efetch.xml"))
    if host == "www.ebi.ac.uk":
        params = dict(request.url.params)
        if request.method == "POST":
            params = dict(httpx.QueryParams(request.content.decode()))
        page = "europepmc_page2.json" if params.get("cursorMark") not in (None, "*") else "europepmc.json"
        return httpx.Response(200, content=fixture_bytes(page))
    if host == "export.arxiv.org":
        return httpx.Response(200, content=fixture_bytes("arxiv.xml"))
    if host == "api.biorxiv.org":
        return httpx.Response(200, content=fixture_bytes("biorxiv.json"))
    if host == "api.semanticscholar.org":
        return httpx.Response(200, content=fixture_bytes("semantic_scholar.json"))
    if host == "api.crossref.org":
        return httpx.Response(200, content=fixture_bytes("crossref.json"))
    return httpx.Response(404)


def make_client(handler=api_router) -> HttpClient:
    return HttpClient(transport=httpx.MockTransport(handler), sleep=lambda s: None)


@pytest.fixture
def client() -> HttpClient:
    return make_client()


@pytest.fixture
def tmp_project(tmp_path, monkeypatch):
    papers = tmp_path / "papers"
    papers.mkdir()
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "PAPERS_DIR", papers)
    monkeypatch.setattr(config, "PAPERS_JSON", papers / "papers.json")
    monkeypatch.setattr(config, "NEW_PAPERS_JSON", papers / "new_papers.json")
    monkeypatch.setattr(config, "STATE_JSON", papers / "state.json")
    monkeypatch.setattr(config, "CURATED_DOIS_FILE", papers / "curated_dois.txt")
    monkeypatch.setattr(config, "README_PATH", tmp_path / "README.md")
    monkeypatch.setattr(config, "CATEGORY_PAGES_DIR", tmp_path / "docs" / "papers")
    monkeypatch.setattr(config, "TEMPLATE_DIR", ROOT / "templates")
    monkeypatch.setattr(config, "EMAIL_RECIPIENTS", [])
    monkeypatch.setattr(config, "HOST_MIN_INTERVAL", {})
    monkeypatch.setattr(config, "TRANSLATIONS_JSON", papers / "translations.json")
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    monkeypatch.setattr(config, "AI_NOTES_DIR", tmp_path / "ai_notes")
    monkeypatch.setattr(config, "FULLTEXT_CACHE_DIR", tmp_path / ".cache" / "fulltext")
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
    return tmp_path
