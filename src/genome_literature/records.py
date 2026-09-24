"""Paper record schema, text cleaning, identifiers and cross-source deduplication.

Unified record schema::

    id                 stable key (normalized DOI, else pmid:/arxiv:/s2:/epmc:/biorxiv: id)
    title, abstract    cleaned plain text
    authors            list of "Family Given" strings
    journal, year, date (YYYY-MM-DD)
    doi, pmid, pmcid, arxiv_id, s2_id, preprint_doi
    url, pdf_url
    source             database the record was first found in
    sources            every database that returned it
    is_preprint        bool
    publication_types  lower-case list (e.g. ["journal article", "review"])
    keywords           author keywords when available
    citations          citation count (max seen across sources)
    categories         research categories (categorizer)
    track, relevance, genome_score, ml_score, dl_methods, tools  (relevance module)
    curated            listed in papers/curated_dois.txt
    first_seen         YYYY-MM-DD the paper entered the database
    fetched_at, updated_at  ISO timestamps
"""

from __future__ import annotations

import html
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from .matching import normalize_text

SOURCE_PRIORITY = ["pubmed", "europepmc", "semantic_scholar", "crossref", "biorxiv", "arxiv", "curated"]

PREPRINT_SERVERS = ("biorxiv", "medrxiv", "arxiv", "research square", "preprints", "ssrn", "chemrxiv")

_TAG_RE = re.compile(r"</?[A-Za-z][\w:.-]*(?:\s[^<>]*)?/?>")
_BLOCK_TAG_RE = re.compile(r"</?(?:p|h\d|br|div|sec|title|jats:p|jats:title|jats:sec|li|ul|ol)\b[^>]*>", re.I)
_HEADING_RE = re.compile(r"<(?:h\d|jats:title|title)\b[^>]*>(.*?)</(?:h\d|jats:title|title)>", re.I | re.S)
_LEADING_ABSTRACT_RE = re.compile(r"^\s*(?:abstract|summary)\s*[:.]?\s+", re.I)
_DOI_PREFIX_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.I)
_ARXIV_VERSION_RE = re.compile(r"v\d+$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def clean_text(text: Any) -> str:
    """Strip HTML/JATS markup, unescape entities, normalize dashes/whitespace."""
    if not text:
        return ""
    s = str(text)
    for _ in range(2):
        s = _BLOCK_TAG_RE.sub(" ", s)
        s = _TAG_RE.sub("", s)
        s = html.unescape(s)
    return normalize_text(s)


def clean_title(text: Any) -> str:
    s = clean_text(text)
    return s[:-1] if s.endswith(".") and not s.endswith("..") else s


def clean_abstract(text: Any) -> str:
    s = _HEADING_RE.sub(lambda m: f" {m.group(1).strip().rstrip(':.')}: ", str(text or ""))
    return _LEADING_ABSTRACT_RE.sub("", clean_text(s))


def normalize_doi(doi: Any) -> str:
    if not doi:
        return ""
    d = _DOI_PREFIX_RE.sub("", str(doi).strip()).strip().rstrip(".").lower()
    return d if d.startswith("10.") else ""


def normalize_arxiv_id(arxiv_id: Any) -> str:
    if not arxiv_id:
        return ""
    a = str(arxiv_id).strip()
    a = re.sub(r"^(?:https?://arxiv\.org/abs/|arxiv:)", "", a, flags=re.I)
    return _ARXIV_VERSION_RE.sub("", a)


def title_key(title: str) -> str:
    """Aggressive normalization used to match the same work across sources."""
    t = unicodedata.normalize("NFKD", clean_text(title)).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()
    return t if len(t) >= 25 else ""


def normalize_date(value: Any, year: Any = None) -> str:
    """Return YYYY-MM-DD, padding missing month/day with 01."""
    if value:
        m = re.match(r"^(\d{4})(?:[-/](\d{1,2}))?(?:[-/](\d{1,2}))?", str(value).strip())
        if m:
            y, mo, d = m.group(1), m.group(2) or "1", m.group(3) or "1"
            mo_i = min(max(int(mo), 1), 12)
            d_i = min(max(int(d), 1), 31)
            return f"{y}-{mo_i:02d}-{d_i:02d}"
    if year:
        try:
            return f"{int(year):04d}-01-01"
        except (TypeError, ValueError):
            pass
    return ""


def detect_preprint(journal: str, doi: str) -> bool:
    j = (journal or "").lower()
    if any(server in j for server in PREPRINT_SERVERS):
        return True
    return doi.startswith(("10.1101/", "10.48550/")) and not j


def make_id(paper: dict[str, Any]) -> str:
    if paper.get("doi"):
        return paper["doi"]
    for key, prefix in (("pmid", "pmid:"), ("arxiv_id", "arxiv:"), ("s2_id", "s2:"), ("epmc_id", "epmc:")):
        if paper.get(key):
            return f"{prefix}{paper[key]}".lower()
    tk = title_key(paper.get("title", ""))
    return f"title:{tk[:80]}" if tk else ""


def new_record(source: str, **fields: Any) -> dict[str, Any]:
    """Build a normalized record from source-specific fields."""
    record = {"source": source, "sources": [source], **fields}
    return normalize_record(record)


def normalize_record(paper: dict[str, Any]) -> dict[str, Any]:
    """Fill defaults and normalize fields in place (also upgrades old DB rows)."""
    p = paper
    p["title"] = clean_title(p.get("title", ""))
    p["abstract"] = clean_abstract(p.get("abstract", ""))
    p["authors"] = [normalize_text(a) for a in (p.get("authors") or []) if a and str(a).strip()]
    p["journal"] = clean_text(p.get("journal", ""))
    p["doi"] = normalize_doi(p.get("doi"))
    p["pmid"] = str(p.get("pmid") or "").strip()
    p["pmcid"] = str(p.get("pmcid") or "").strip()
    p["arxiv_id"] = normalize_arxiv_id(p.get("arxiv_id"))
    p["s2_id"] = str(p.get("s2_id") or "").strip()
    p["preprint_doi"] = normalize_doi(p.get("preprint_doi"))
    p["source"] = p.get("source") or "unknown"
    sources = p.get("sources") or [p["source"]]
    p["sources"] = sorted(set(sources), key=_source_rank)

    old_id = str(p.get("id") or "").strip()
    if old_id.startswith("pmid:") and not p["pmid"]:
        p["pmid"] = old_id[5:]
    if old_id.startswith("arxiv:") and not p["arxiv_id"]:
        p["arxiv_id"] = normalize_arxiv_id(old_id[6:])
    if old_id.startswith("10.") and not p["doi"]:
        p["doi"] = normalize_doi(old_id)

    p["date"] = normalize_date(p.get("date"), p.get("year"))
    horizon = (datetime.now(timezone.utc) + timedelta(days=60)).strftime("%Y-%m-%d")
    if p["date"] > horizon:
        seen = str(p.get("first_seen") or p.get("fetched_at") or "")[:10]
        p["date"] = seen if len(seen) == 10 else today()
        p["year"] = int(p["date"][:4])
    try:
        p["year"] = int(p.get("year") or (p["date"][:4] if p["date"] else 0))
    except (TypeError, ValueError):
        p["year"] = int(p["date"][:4]) if p["date"] else 0
    if p["date"] and p["year"] and not p["date"].startswith(str(p["year"])):
        p["year"] = int(p["date"][:4])

    p["is_preprint"] = bool(p.get("is_preprint")) or detect_preprint(p["journal"], p["doi"])
    p["publication_types"] = sorted({str(t).strip().lower() for t in (p.get("publication_types") or []) if t})
    p["keywords"] = [clean_text(k) for k in (p.get("keywords") or []) if k]
    try:
        p["citations"] = int(p.get("citations") or 0)
    except (TypeError, ValueError):
        p["citations"] = 0
    p["url"] = p.get("url") or _best_url(p)
    p["pdf_url"] = p.get("pdf_url") or ""
    p["categories"] = list(p.get("categories") or [])
    p["curated"] = bool(p.get("curated"))
    p["fetched_at"] = p.get("fetched_at") or now_iso()
    p["id"] = old_id.lower() if old_id else make_id(p)
    if p["id"].startswith("10."):
        p["id"] = normalize_doi(p["id"]) or p["id"]
    return p


def _best_url(p: dict[str, Any]) -> str:
    if p.get("doi"):
        return f"https://doi.org/{p['doi']}"
    if p.get("pmid"):
        return f"https://pubmed.ncbi.nlm.nih.gov/{p['pmid']}/"
    if p.get("arxiv_id"):
        return f"https://arxiv.org/abs/{p['arxiv_id']}"
    return ""


def _source_rank(source: str) -> int:
    return SOURCE_PRIORITY.index(source) if source in SOURCE_PRIORITY else len(SOURCE_PRIORITY)


def identifiers(paper: dict[str, Any]) -> set[str]:
    keys = {f"id:{paper['id']}"} if paper.get("id") else set()
    if paper.get("doi"):
        keys.add(f"doi:{paper['doi']}")
    if paper.get("preprint_doi"):
        keys.add(f"doi:{paper['preprint_doi']}")
    if paper.get("pmid"):
        keys.add(f"pmid:{paper['pmid']}")
    if paper.get("arxiv_id"):
        keys.add(f"arxiv:{paper['arxiv_id'].lower()}")
    if paper.get("s2_id"):
        keys.add(f"s2:{paper['s2_id']}")
    tk = title_key(paper.get("title", ""))
    if tk:
        keys.add(f"title:{tk}")
    return keys


def merge_into(base: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    """Merge metadata from ``other`` into ``base`` without changing base['id']."""
    if base.get("is_preprint") and not other.get("is_preprint") and other.get("journal"):
        if base.get("doi") and other.get("doi") and base["doi"] != other["doi"]:
            base["preprint_doi"] = base.get("preprint_doi") or base["doi"]
            base["doi"] = other["doi"]
        base["journal"] = other["journal"]
        base["is_preprint"] = False
        if other.get("date"):
            base["date"], base["year"] = other["date"], other.get("year") or base.get("year")
        base["url"] = other.get("url") or base.get("url")
    elif other.get("is_preprint") and other.get("doi") and base.get("doi") != other["doi"]:
        base["preprint_doi"] = base.get("preprint_doi") or other["doi"]

    for key in ("doi", "pmid", "pmcid", "arxiv_id", "s2_id", "journal", "date", "url", "pdf_url"):
        if not base.get(key) and other.get(key):
            base[key] = other[key]
    if not base.get("year") and other.get("year"):
        base["year"] = other["year"]
    if len(other.get("abstract") or "") > len(base.get("abstract") or ""):
        base["abstract"] = other["abstract"]
    if len(other.get("authors") or []) > len(base.get("authors") or []):
        base["authors"] = other["authors"]
    base["citations"] = max(int(base.get("citations") or 0), int(other.get("citations") or 0))
    base["publication_types"] = sorted(set(base.get("publication_types") or []) | set(other.get("publication_types") or []))
    base["keywords"] = list(dict.fromkeys((base.get("keywords") or []) + (other.get("keywords") or [])))
    base["sources"] = sorted(set(base.get("sources") or []) | set(other.get("sources") or []), key=_source_rank)
    base["curated"] = bool(base.get("curated") or other.get("curated"))
    return base


class PaperIndex:
    """Identifier index used to deduplicate records across sources."""

    def __init__(self, papers: Iterable[dict[str, Any]] = ()):
        self.papers: list[dict[str, Any]] = []
        self._keys: dict[str, dict[str, Any]] = {}
        for p in papers:
            self.add(p)

    def find(self, paper: dict[str, Any]) -> dict[str, Any] | None:
        for key in identifiers(paper):
            hit = self._keys.get(key)
            if hit is not None:
                return hit
        return None

    def add(self, paper: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Insert or merge; returns (stored record, was_new)."""
        existing = self.find(paper)
        if existing is not None:
            merge_into(existing, paper)
            self._register(existing)
            return existing, False
        self.papers.append(paper)
        self._register(paper)
        return paper, True

    def _register(self, paper: dict[str, Any]) -> None:
        for key in identifiers(paper):
            self._keys.setdefault(key, paper)


def deduplicate(papers: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(papers, key=lambda p: _source_rank(p.get("source", "")))
    return PaperIndex(ordered).papers
