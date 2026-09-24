from __future__ import annotations

from genome_literature.records import (
    clean_abstract, clean_title, deduplicate, new_record, normalize_doi, normalize_record, title_key,
)
from genome_literature.storage import load_curated_dois, merge_papers


def test_text_cleaning():
    assert clean_title("Loop &amp; <i>TAD</i> calling&#8212;fast.") == "Loop & TAD calling-fast"
    assert clean_abstract("<jats:title>Abstract</jats:title><jats:p>Hi-C maps.</jats:p>") == "Hi-C maps."
    assert normalize_doi("https://doi.org/10.1038/ABC.1") == "10.1038/abc.1"
    assert normalize_doi("not a doi") == ""
    assert title_key("Hi-C: a Method!") == ""
    assert title_key("Predicting 3D Genome Folding — from DNA") == title_key("predicting 3d genome folding from dna")


def test_old_database_rows_are_upgraded():
    old = {"id": "pmid:123", "title": "Chromatin loops in Hi-C", "authors": ["A B"], "abstract": "",
           "journal": "bioRxiv (preprint)", "year": 2021, "date": "2021-3-7", "doi": "", "url": "",
           "source": "biorxiv", "categories": ["Other"], "fetched_at": "2024-01-01T00:00:00"}
    p = normalize_record(old)
    assert p["id"] == "pmid:123" and p["pmid"] == "123"
    assert p["date"] == "2021-03-07" and p["is_preprint"]
    assert p["sources"] == ["biorxiv"] and p["citations"] == 0


def test_preprint_and_published_version_are_merged():
    preprint = new_record("biorxiv", title="Graph neural networks predict enhancer-promoter interactions from Micro-C",
                          doi="10.1101/2024.01.01.000001", journal="bioRxiv (preprint)", date="2024-01-01",
                          abstract="short")
    published = new_record("pubmed", title="Graph neural networks predict enhancer–promoter interactions from Micro-C.",
                           doi="10.1038/s00000-024-1", journal="Nature Genetics", date="2024-09-01", pmid="555",
                           abstract="a much longer abstract about Micro-C and graph neural networks")
    merged = deduplicate([preprint, published])
    assert len(merged) == 1
    m = merged[0]
    assert m["doi"] == "10.1038/s00000-024-1" and m["preprint_doi"] == "10.1101/2024.01.01.000001"
    assert m["journal"] == "Nature Genetics" and not m["is_preprint"]
    assert m["pmid"] == "555" and m["sources"] == ["pubmed", "biorxiv"]
    assert m["abstract"].startswith("a much longer")


def test_merge_keeps_existing_ids_and_first_seen():
    existing = [normalize_record({"id": "arxiv:2401.00001", "title": "HiCFormer: transformers for Hi-C contact maps",
                                  "arxiv_id": "2401.00001", "source": "arxiv", "first_seen": "2024-01-05",
                                  "journal": "arXiv (preprint)"})]
    later = new_record("pubmed", title="HiCFormer: Transformers for Hi-C Contact Maps", doi="10.1/x.2",
                       journal="Genome Biology", pmid="9", date="2024-06-01")
    brand_new = new_record("europepmc", title="Another chromatin loop caller using deep learning", doi="10.1/y")
    merged, new = merge_papers(existing, [later, brand_new], first_seen="2024-07-01")
    assert len(merged) == 2 and [p["doi"] for p in new] == ["10.1/y"]
    kept = merged[0]
    assert kept["id"] == "arxiv:2401.00001" and kept["first_seen"] == "2024-01-05"
    assert kept["doi"] == "10.1/x.2" and kept["journal"] == "Genome Biology"
    assert new[0]["first_seen"] == "2024-07-01"


def test_curated_doi_file(tmp_project):
    from genome_literature import config
    config.CURATED_DOIS_FILE.write_text("10.1038/ABC  Akita\n\nnot-a-doi\n10.1126/science.1  Hi-C\n", encoding="utf-8")
    assert load_curated_dois() == ["10.1038/abc", "10.1126/science.1"]


def test_escaped_markup_in_titles_is_removed():
    assert clean_title("Hybrids of F&lt;sub&gt;1&lt;/sub&gt; males") == "Hybrids of F1 males"
    assert clean_title("Loops with p < 0.05 and q > 1") == "Loops with p < 0.05 and q > 1"


def test_far_future_issue_dates_fall_back_to_first_seen():
    p = normalize_record({"title": "Hi-C chromatin loops in plants", "date": "2099-01-01", "year": 2099,
                          "first_seen": "2026-09-01", "source": "pubmed"})
    assert p["date"] == "2026-09-01" and p["year"] == 2026
