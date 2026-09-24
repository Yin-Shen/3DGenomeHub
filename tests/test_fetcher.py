from __future__ import annotations

import httpx

from conftest import fixture_bytes, make_client
from genome_literature import config
from genome_literature.fetcher import (
    build_arxiv_query, build_europepmc_query, build_pubmed_query, fetch_all_papers, fetch_arxiv,
    fetch_biorxiv_recent, fetch_crossref, fetch_europepmc, fetch_pubmed, fetch_semantic_scholar,
    parse_arxiv_feed, parse_pubmed_xml,
)


def test_pubmed_parser_uses_article_doi_not_reference_doi():
    papers = parse_pubmed_xml(fixture_bytes("pubmed_efetch.xml"))
    assert len(papers) == 3
    first, assembly, review = papers
    assert first["doi"] == "10.1000/test.3dgenome.2024"
    assert first["id"] == "10.1000/test.3dgenome.2024"
    assert first["pmid"] == "39000001" and first["pmcid"] == "PMC1234567"
    assert first["title"] == "Predicting 3D genome folding from DNA sequence with a convolutional neural network"
    assert first["abstract"].startswith("Background: Hi-C contact maps")
    assert first["authors"] == ["Doe Jane", "Roe Richard", "4D Nucleome Consortium"]
    assert first["date"] == "2024-02-15" and first["year"] == 2024
    assert first["keywords"] == ["Hi-C", "deep learning"]
    assert assembly["doi"] == "" and assembly["id"] == "pmid:39000002"
    assert assembly["date"] == "2023-11-01"
    assert review["date"] == "2022-12-01"
    assert "review" in review["publication_types"]


def test_fetch_pubmed_with_date_window(client):
    seen = {}

    def handler(request: httpx.Request):
        if request.url.path.endswith("esearch.fcgi"):
            seen.update(dict(request.url.params))
        from conftest import api_router
        return api_router(request)

    papers = fetch_pubmed("q", max_results=5, since="2024-01-01", until="2024-02-01", client=make_client(handler))
    assert len(papers) == 3
    assert seen["mindate"] == "2024/01/01" and seen["maxdate"] == "2024/02/01" and seen["datetype"] == "edat"
    assert seen["sort"] == "relevance"


def test_europepmc_parser_and_cursor_paging(client):
    papers = fetch_europepmc("x", max_results=50, since="2024-01-01", client=client)
    assert len(papers) == 2
    journal, preprint = papers
    assert journal["journal"] == "Nature Methods"
    assert journal["citations"] == 42
    assert journal["pdf_url"].startswith("https://europepmc.org/articles/PMC1234567")
    assert "<h4>" not in journal["abstract"] and journal["abstract"].startswith("Background: Hi-C")
    assert preprint["is_preprint"] and preprint["journal"] == "bioRxiv (preprint)"
    assert preprint["title"] == "Graph neural networks predict enhancer-promoter interactions from Micro-C maps"


def test_europepmc_long_query_uses_post_then_falls_back_to_get():
    methods = []

    def handler(request: httpx.Request):
        methods.append(request.method)
        if request.method == "POST":
            return httpx.Response(405)
        return httpx.Response(200, content=fixture_bytes("europepmc_page2.json"))

    fetch_europepmc("x" * 2000, client=make_client(handler))
    assert methods == ["POST", "GET"]


def test_arxiv_parser_handles_versions_journal_refs_and_errors():
    papers = parse_arxiv_feed(fixture_bytes("arxiv.xml"))
    assert [p["arxiv_id"] for p in papers] == ["2406.01234", "2301.04567"]
    diffusion, protein = papers
    assert diffusion["title"] == "HiCDiffusion: Diffusion Models for Generating Chromatin Contact Maps"
    assert diffusion["is_preprint"] and diffusion["id"] == "arxiv:2406.01234"
    assert diffusion["pdf_url"] == "https://arxiv.org/pdf/2406.01234v2"
    assert diffusion["url"] == "https://arxiv.org/abs/2406.01234"
    assert protein["doi"] == "10.1093/bioinformatics/btad001" and not protein["is_preprint"]
    assert parse_arxiv_feed(fixture_bytes("arxiv_error.xml")) == []


def test_arxiv_date_window_in_query():
    seen = {}

    def handler(request):
        seen.update(dict(request.url.params))
        return httpx.Response(200, content=fixture_bytes("arxiv.xml"))

    fetch_arxiv("abs:x", max_results=10, since="2024-06-01", until="2024-06-30", client=make_client(handler))
    assert "submittedDate:[202406010000 TO 202406302359]" in seen["search_query"]


def test_biorxiv_scan_keeps_latest_version_and_prefilters(client):
    papers = fetch_biorxiv_recent("2025-01-01", "2025-01-31", client=client)
    assert len(papers) == 1
    assert papers[0]["abstract"].endswith("(revised).")
    assert papers[0]["doi"] == "10.1101/2025.01.10.632001"
    assert papers[0]["is_preprint"]


def test_semantic_scholar_and_crossref_parsers(client):
    s2 = fetch_semantic_scholar("q", client=client)
    assert s2[0]["doi"] == "10.1000/test.3dgenome.2024" and s2[0]["citations"] == 57
    assert s2[1]["arxiv_id"] == "2503.00999" and s2[1]["is_preprint"]
    cr = fetch_crossref("q", client=client)
    assert cr[0]["abstract"].startswith("We present an algorithm for calling TADs")
    assert cr[0]["date"] == "2024-05-18"
    assert cr[1]["year"] == 2020


def test_query_builders_expand_plurals_but_not_acronyms():
    groups = [["chromatin loop", "Hi-C", "TAD"], ["deep learning"]]
    pq = build_pubmed_query(groups)
    assert '"chromatin loop*"[tiab]' in pq and '"Hi-C"[tiab]' in pq and '"TAD"[tiab]' in pq
    assert '"deep learning"[tiab]' in pq
    eq = build_europepmc_query(groups)
    assert 'ABSTRACT:"chromatin loops"' in eq and 'TITLE:"Hi-C"' in eq
    assert build_arxiv_query(groups).count(" AND ") == 1


def test_fetch_all_papers_dedups_across_sources_and_reports(monkeypatch, client):
    monkeypatch.setattr(config, "SEARCH_TOPICS", config.SEARCH_TOPICS[:1])
    report = {}
    papers = fetch_all_papers(since="2024-01-01", until="2025-01-31", report=report, client=client,
                              curated_dois=["10.1000/test.3dgenome.2024"])
    assert set(report["by_source"]) == {"curated", "pubmed", "europepmc", "arxiv", "semantic_scholar", "crossref", "biorxiv"}
    assert report["errors"] == []
    same = [p for p in papers if p.get("doi") == "10.1000/test.3dgenome.2024"]
    assert len(same) == 1
    merged = same[0]
    assert {"pubmed", "europepmc", "semantic_scholar"} <= set(merged["sources"])
    assert merged["citations"] == 57 and merged["curated"]
    gnn = [p for p in papers if p.get("doi") == "10.1101/2025.01.10.632001"]
    assert len(gnn) == 1 and {"europepmc", "biorxiv"} <= set(gnn[0]["sources"])


def test_failing_source_is_reported_not_fatal(monkeypatch):
    monkeypatch.setattr(config, "SEARCH_TOPICS", config.SEARCH_TOPICS[:1])

    def handler(request):
        if request.url.host == "api.semanticscholar.org":
            return httpx.Response(429, headers={"Retry-After": "0"})
        from conftest import api_router
        return api_router(request)

    report = {}
    papers = fetch_all_papers(since="2025-01-01", report=report, client=make_client(handler))
    assert papers
    assert {e["source"] for e in report["errors"]} == {"semantic_scholar"}


def test_crossref_and_s2_retry_without_unsupported_params():
    calls = []

    def handler(request):
        params = dict(request.url.params)
        calls.append((request.url.host, sorted(params)))
        if request.url.host == "api.crossref.org" and "select" in params:
            return httpx.Response(400, json={"status": "failed"})
        if request.url.host == "api.semanticscholar.org" and "publicationDateOrYear" in params:
            return httpx.Response(400, json={"error": "bad param"})
        from conftest import api_router
        return api_router(request)

    c = make_client(handler)
    assert len(fetch_crossref("q", client=c)) == 2
    s2 = fetch_semantic_scholar("q", since="2025-01-01", until="2025-12-31", client=c)
    assert [p["arxiv_id"] for p in s2] == ["2503.00999"]
    assert len(calls) == 4


def test_repeatedly_failing_source_is_skipped(monkeypatch):
    monkeypatch.setattr(config, "SEARCH_TOPICS", config.SEARCH_TOPICS[:3])
    calls = {"s2": 0}

    def handler(request):
        if request.url.host == "api.semanticscholar.org":
            calls["s2"] += 1
            return httpx.Response(429, headers={"Retry-After": "0"})
        from conftest import api_router
        return api_router(request)

    report = {}
    fetch_all_papers(since="2025-01-01", report=report, client=make_client(handler))
    s2_jobs = sum(len(t["plain"]) for t in config.SEARCH_TOPICS)
    assert len([e for e in report["errors"] if e["source"] == "semantic_scholar"]) == config.SOURCE_FAILURE_LIMIT
    assert report["skipped"]["semantic_scholar"] == s2_jobs - config.SOURCE_FAILURE_LIMIT
    assert calls["s2"] == config.SOURCE_FAILURE_LIMIT * (config.HTTP_MAX_RETRIES + 1)


def test_non_json_response_is_explained():
    def handler(request):
        return httpx.Response(403, content=b"<html>Just a moment...</html>", headers={"content-type": "text/html"})

    import pytest
    with pytest.raises(httpx.HTTPStatusError):
        fetch_biorxiv_recent("2025-01-01", "2025-01-02", client=make_client(handler))

    def handler_ok_html(request):
        return httpx.Response(200, content=b"<html>Just a moment...</html>", headers={"content-type": "text/html"})

    with pytest.raises(ValueError, match="non-JSON response from api.biorxiv.org \\(HTTP 200, text/html\\)"):
        fetch_biorxiv_recent("2025-01-01", "2025-01-02", client=make_client(handler_ok_html))


def test_future_issue_date_falls_back_to_pubmed_entry_date():
    xml = b"""<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>1</PMID><Article>
    <Journal><JournalIssue><PubDate><Year>2099</Year></PubDate></JournalIssue><Title>Methods Mol Biol</Title></Journal>
    <ArticleTitle>Hi-C analysis of chromatin loops</ArticleTitle></Article></MedlineCitation>
    <PubmedData><History><PubMedPubDate PubStatus="pubmed"><Year>2026</Year><Month>9</Month><Day>1</Day></PubMedPubDate></History>
    </PubmedData></PubmedArticle></PubmedArticleSet>"""
    assert parse_pubmed_xml(xml)[0]["date"] == "2026-09-01"


def test_pubmed_esearch_tolerates_control_characters():
    def handler(request):
        if request.url.path.endswith("esearch.fcgi"):
            body = '{"esearchresult": {"idlist": ["39000001"], "querytranslation": "a\tb\x01c"}}'
            return httpx.Response(200, content=body.encode(), headers={"content-type": "application/json"})
        from conftest import api_router
        return api_router(request)

    papers = fetch_pubmed("q", max_results=5, client=make_client(handler))
    assert len(papers) == 3
