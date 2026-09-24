from __future__ import annotations

import json

from conftest import make_client
from genome_literature import config, fetcher, pipeline
from genome_literature.readme_generator import github_anchor, md_escape
from genome_literature.records import normalize_record
from genome_literature.storage import load_papers, load_state, save_papers


def _patch_fetch(monkeypatch, calls):
    client = make_client()
    monkeypatch.setattr(config, "SEARCH_TOPICS", config.SEARCH_TOPICS[:1])

    def fake_fetch_all(**kwargs):
        calls.append(kwargs)
        kwargs.pop("progress", None)
        return fetcher.fetch_all_papers(client=client, **kwargs)

    monkeypatch.setattr(pipeline, "fetch_all_papers", fake_fetch_all)


def test_full_pipeline_twice(tmp_project, monkeypatch):
    calls = []
    _patch_fetch(monkeypatch, calls)
    noisy = normalize_record({"id": "10.5555/noise", "title": "Metadata status of organ donors", "doi": "10.5555/noise",
                              "source": "crossref", "abstract": "Not about chromatin."})
    save_papers([noisy])

    first = pipeline.run_pipeline(skip_email=True)
    assert first["success"] and first["mode"] == "incremental"
    assert first["pruned_count"] == 1
    papers = load_papers()
    ids = {p["id"] for p in papers}
    assert "10.5555/noise" not in ids
    assert "10.1000/test.3dgenome.2024" in ids
    assert not any("assembly" in p["title"].lower() for p in papers)
    assert not any("protein" in p["title"].lower() for p in papers)
    assert not any(p["title"].startswith("Metadata") for p in papers)
    assert all(p["categories"] and p["track"] and "relevance" in p for p in papers)
    assert all(not k.startswith("_") for p in papers for k in p)

    state = load_state()
    assert set(state["last_new_ids"]) == {p["id"] for p in papers}
    assert state["sources"]["pubmed"]["until"] == first["run_date"]

    readme = config.README_PATH.read_text(encoding="utf-8")
    assert "## Latest papers" in readme and "## Browse by topic" in readme
    assert "Predicting 3D genome folding" in readme
    pages = sorted(p.name for p in config.CATEGORY_PAGES_DIR.glob("*.md"))
    assert "ai-ml-3d-genome.md" in pages
    assert "epigenomics-sequence-based-prediction.md" in pages
    for link in [l for l in readme.split("(docs/papers/")[1:]]:
        assert (config.CATEGORY_PAGES_DIR / link.split(")")[0]).exists()

    second = pipeline.run_pipeline(skip_email=True)
    assert second["new_count"] == 0
    assert second["total_count"] == first["total_count"]
    assert calls[1]["since"] is not None
    assert json.loads(config.STATE_JSON.read_text())["runs"][-1]["new"] == 0


def test_empty_database_triggers_backfill(tmp_project, monkeypatch):
    calls = []
    _patch_fetch(monkeypatch, calls)
    result = pipeline.run_pipeline(skip_email=True, skip_readme=True)
    assert result["mode"] == "backfill" and calls[0]["since"] is None and calls[0]["backfill"] is True


def test_resolve_window_uses_oldest_successful_source():
    from datetime import datetime, timedelta
    from genome_literature.records import today

    def days_ago(n):
        return (datetime.strptime(today(), "%Y-%m-%d") - timedelta(days=n)).strftime("%Y-%m-%d")

    state = {"sources": {"pubmed": {"until": days_ago(5)}, "arxiv": {"until": days_ago(14)}}}
    since, backfill = pipeline.resolve_window(state, True, None, False, ["pubmed", "arxiv"])
    assert since == days_ago(14 + config.INCREMENTAL_OVERLAP_DAYS) and not backfill


def test_stale_generated_pages_are_removed(tmp_project, monkeypatch):
    from genome_literature.readme_generator import GENERATED_MARKER, write_outputs
    config.CATEGORY_PAGES_DIR.mkdir(parents=True)
    stale = config.CATEGORY_PAGES_DIR / "old-topic.md"
    stale.write_text(GENERATED_MARKER + "\nold", encoding="utf-8")
    handwritten = config.CATEGORY_PAGES_DIR / "notes.md"
    handwritten.write_text("my notes", encoding="utf-8")
    write_outputs([])
    assert not stale.exists() and handwritten.exists()
    assert "The database is empty" in config.README_PATH.read_text(encoding="utf-8")


def test_github_anchor_and_escaping():
    assert github_anchor("Hi-C Enhancement & Super-Resolution") == "hi-c-enhancement--super-resolution"
    assert github_anchor("Most-cited AI/ML papers") == "most-cited-aiml-papers"
    assert md_escape("a|b [c] *d*") == "a\\|b \\[c\\] \\*d\\*"


def test_incremental_window_is_capped():
    state = {"sources": {"pubmed": {"until": "2020-01-01"}}}
    since, _ = pipeline.resolve_window(state, True, None, False, ["pubmed"])
    from datetime import datetime, timedelta
    from genome_literature.records import today
    earliest = (datetime.strptime(today(), "%Y-%m-%d") - timedelta(days=config.MAX_INCREMENTAL_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    assert since == earliest


def test_landmark_flag_follows_curated_list(tmp_project):
    config.CURATED_DOIS_FILE.write_text("10.1000/listed  Landmark\n", encoding="utf-8")
    listed = normalize_record({"title": "Chromatin loops in Hi-C maps of human cells", "doi": "10.1000/listed",
                               "abstract": "Hi-C chromatin loops and TADs.", "source": "pubmed"})
    unlisted = normalize_record({"title": "Topologically associating domains in Hi-C maps of fly embryos",
                                 "doi": "10.1000/other", "abstract": "Hi-C TADs and chromatin loops.",
                                 "source": "pubmed", "curated": True})
    kept, _ = pipeline.refresh_annotations([listed, unlisted])
    flags = {p["doi"]: p["curated"] for p in kept}
    assert flags == {"10.1000/listed": True, "10.1000/other": False}


def test_late_duplicates_are_merged_on_refresh():
    a = normalize_record({"title": "Deep learning of Hi-C chromatin loops in human cells", "doi": "10.1/a",
                          "abstract": "Hi-C chromatin loops predicted by a convolutional neural network.", "source": "pubmed"})
    b = normalize_record({"title": "A different working title for the Hi-C loop paper", "pmid": "77",
                          "abstract": "Hi-C chromatin loops predicted by a convolutional neural network.", "source": "europepmc"})
    a["pmid"] = "77"
    kept, _ = pipeline.refresh_annotations([a, b])
    assert len(kept) == 1
