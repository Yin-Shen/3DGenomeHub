"""Fetch papers from PubMed (NCBI E-utilities), bioRxiv, and arXiv APIs.

Each fetcher returns a list of Paper dicts with unified schema:
  {
    "id": str,           # unique identifier (DOI or source-specific ID)
    "title": str,
    "authors": list[str],
    "abstract": str,
    "journal": str,
    "year": int,
    "date": str,         # YYYY-MM-DD
    "doi": str,
    "url": str,
    "source": str,       # "pubmed" | "biorxiv" | "arxiv"
    "categories": list[str],   # filled later by categorizer
    "fetched_at": str,   # ISO timestamp
  }
"""

from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx

from . import config

logger = logging.getLogger(__name__)

# Shared HTTP client settings
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_HEADERS = {"User-Agent": "3DGenomeHub/2.0 (https://github.com/Yin-Shen/3DGenomeHub)"}


# ---------------------------------------------------------------------------
# PubMed via NCBI E-utilities
# ---------------------------------------------------------------------------

PUBMED_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def fetch_pubmed(query: str, max_results: int = config.MAX_RESULTS_PER_QUERY) -> list[dict[str, Any]]:
    """Search PubMed and return structured paper records."""
    papers: list[dict[str, Any]] = []
    try:
        # Step 1: esearch to get PMIDs
        params = {
            "db": "pubmed",
            "term": query,
            "retmax": str(max_results),
            "sort": "date",
            "retmode": "json",
        }
        with httpx.Client(timeout=_TIMEOUT, headers=_HEADERS) as client:
            resp = client.get(PUBMED_ESEARCH, params=params)
            resp.raise_for_status()
            data = resp.json()

        id_list = data.get("esearchresult", {}).get("idlist", [])
        if not id_list:
            return papers

        # Step 2: efetch to get full records in XML
        time.sleep(0.4)  # respect NCBI rate limit
        with httpx.Client(timeout=_TIMEOUT, headers=_HEADERS) as client:
            resp = client.get(
                PUBMED_EFETCH,
                params={
                    "db": "pubmed",
                    "id": ",".join(id_list),
                    "retmode": "xml",
                },
            )
            resp.raise_for_status()

        root = ET.fromstring(resp.text)
        for article_el in root.findall(".//PubmedArticle"):
            paper = _parse_pubmed_article(article_el)
            if paper:
                papers.append(paper)

    except Exception:
        logger.exception("PubMed fetch failed for query: %s", query)

    return papers


def _parse_pubmed_article(article_el: ET.Element) -> dict[str, Any] | None:
    """Parse a single PubmedArticle XML element."""
    try:
        medline = article_el.find(".//MedlineCitation")
        if medline is None:
            return None

        pmid_el = medline.find("PMID")
        pmid = pmid_el.text if pmid_el is not None else ""

        art = medline.find("Article")
        if art is None:
            return None

        # Title
        title_el = art.find("ArticleTitle")
        title = _xml_text(title_el)
        if not title:
            return None

        # Abstract
        abstract_parts = []
        abstract_el = art.find("Abstract")
        if abstract_el is not None:
            for at in abstract_el.findall("AbstractText"):
                label = at.get("Label", "")
                text = _xml_text(at)
                if label and text:
                    abstract_parts.append(f"{label}: {text}")
                elif text:
                    abstract_parts.append(text)
        abstract = " ".join(abstract_parts)

        # Authors
        authors = []
        for author_el in art.findall(".//Author"):
            last = author_el.findtext("LastName", "")
            fore = author_el.findtext("ForeName", "")
            if last:
                authors.append(f"{last} {fore}".strip())

        # Journal
        journal_el = art.find("Journal/Title")
        journal = journal_el.text if journal_el is not None else ""

        # Date
        year, date_str = _extract_pubmed_date(art)

        # DOI
        doi = ""
        for eid in article_el.findall(".//ArticleId"):
            if eid.get("IdType") == "doi":
                doi = eid.text or ""
                break

        url = f"https://doi.org/{doi}" if doi else f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"

        return {
            "id": doi if doi else f"pmid:{pmid}",
            "title": _clean_text(title),
            "authors": authors,
            "abstract": _clean_text(abstract),
            "journal": journal,
            "year": year,
            "date": date_str,
            "doi": doi,
            "url": url,
            "source": "pubmed",
            "categories": [],
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        logger.exception("Failed to parse PubMed article")
        return None


def _extract_pubmed_date(art_el: ET.Element) -> tuple[int, str]:
    """Extract publication date from Article element."""
    # Try ArticleDate first (electronic publication)
    ad = art_el.find("ArticleDate")
    if ad is not None:
        y = ad.findtext("Year", "")
        m = ad.findtext("Month", "01")
        d = ad.findtext("Day", "01")
        if y:
            return int(y), f"{y}-{m.zfill(2)}-{d.zfill(2)}"

    # Fall back to Journal PubDate
    pd = art_el.find("Journal/JournalIssue/PubDate")
    if pd is not None:
        y = pd.findtext("Year", "")
        m = pd.findtext("Month", "01")
        d = pd.findtext("Day", "01")
        if y:
            # Month might be "Jan", "Feb", etc.
            month_map = {
                "jan": "01", "feb": "02", "mar": "03", "apr": "04",
                "may": "05", "jun": "06", "jul": "07", "aug": "08",
                "sep": "09", "oct": "10", "nov": "11", "dec": "12",
            }
            m = month_map.get(m.lower()[:3], m.zfill(2))
            return int(y), f"{y}-{m}-{d.zfill(2)}"

    return datetime.now().year, datetime.now().strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# bioRxiv / medRxiv API
# ---------------------------------------------------------------------------

BIORXIV_API = "https://api.biorxiv.org/details/biorxiv"


def fetch_biorxiv(query: str, max_results: int = config.MAX_RESULTS_PER_QUERY) -> list[dict[str, Any]]:
    """Search bioRxiv for recent preprints matching the query.

    bioRxiv content API returns preprints by date range.  We fetch the last
    365 days and filter by keyword matching on title + abstract.
    """
    papers: list[dict[str, Any]] = []
    try:
        today = datetime.now()
        start_date = today.replace(year=today.year - 1).strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")

        url = f"{BIORXIV_API}/{start_date}/{end_date}/0/{max_results}"
        with httpx.Client(timeout=_TIMEOUT, headers=_HEADERS) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()

        collection = data.get("collection", [])
        query_terms = [t.strip().lower() for t in re.split(r"\s+", query.lower()) if len(t.strip()) > 2]

        for item in collection:
            title = item.get("title", "")
            abstract = item.get("abstract", "")
            text = f"{title} {abstract}".lower()

            # Check if enough query terms appear
            matches = sum(1 for t in query_terms if t in text)
            if matches < min(2, len(query_terms)):
                continue

            doi = item.get("doi", "")
            date_str = item.get("date", "")
            year = int(date_str[:4]) if date_str and len(date_str) >= 4 else today.year

            authors_raw = item.get("authors", "")
            authors = [a.strip() for a in authors_raw.split(";") if a.strip()]

            papers.append({
                "id": f"10.1101/{doi}" if doi and not doi.startswith("10.") else doi,
                "title": _clean_text(title),
                "authors": authors,
                "abstract": _clean_text(abstract),
                "journal": "bioRxiv (preprint)",
                "year": year,
                "date": date_str,
                "doi": f"10.1101/{doi}" if doi and not doi.startswith("10.") else doi,
                "url": f"https://doi.org/10.1101/{doi}" if doi and not doi.startswith("10.") else f"https://doi.org/{doi}",
                "source": "biorxiv",
                "categories": [],
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            })

    except Exception:
        logger.exception("bioRxiv fetch failed for query: %s", query)

    return papers


# ---------------------------------------------------------------------------
# arXiv API
# ---------------------------------------------------------------------------

ARXIV_API = "http://export.arxiv.org/api/query"


def fetch_arxiv(query: str, max_results: int = config.MAX_RESULTS_PER_QUERY) -> list[dict[str, Any]]:
    """Search arXiv for papers matching the query."""
    papers: list[dict[str, Any]] = []
    try:
        search_query = f"all:{quote_plus(query)}"
        params = {
            "search_query": search_query,
            "start": "0",
            "max_results": str(max_results),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        with httpx.Client(timeout=_TIMEOUT, headers=_HEADERS) as client:
            resp = client.get(ARXIV_API, params=params)
            resp.raise_for_status()

        root = ET.fromstring(resp.text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        for entry in root.findall("atom:entry", ns):
            arxiv_id = entry.findtext("atom:id", "", ns).strip()
            # Extract just the ID part
            short_id = arxiv_id.split("/abs/")[-1] if "/abs/" in arxiv_id else arxiv_id.split("/")[-1]

            title = entry.findtext("atom:title", "", ns).strip()
            title = re.sub(r"\s+", " ", title)

            abstract = entry.findtext("atom:summary", "", ns).strip()
            abstract = re.sub(r"\s+", " ", abstract)

            authors = []
            for author_el in entry.findall("atom:author", ns):
                name = author_el.findtext("atom:name", "", ns).strip()
                if name:
                    authors.append(name)

            published = entry.findtext("atom:published", "", ns)
            date_str = published[:10] if published else ""
            year = int(date_str[:4]) if date_str else datetime.now().year

            # Look for DOI in links
            doi = ""
            for link in entry.findall("atom:link", ns):
                href = link.get("href", "")
                if "doi.org" in href:
                    doi = href.replace("https://doi.org/", "").replace("http://doi.org/", "")
                    break

            papers.append({
                "id": doi if doi else f"arxiv:{short_id}",
                "title": _clean_text(title),
                "authors": authors,
                "abstract": _clean_text(abstract),
                "journal": "arXiv (preprint)",
                "year": year,
                "date": date_str,
                "doi": doi,
                "url": arxiv_id if arxiv_id.startswith("http") else f"https://arxiv.org/abs/{short_id}",
                "source": "arxiv",
                "categories": [],
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            })

    except Exception:
        logger.exception("arXiv fetch failed for query: %s", query)

    return papers


# ---------------------------------------------------------------------------
# Unified fetch interface
# ---------------------------------------------------------------------------

FETCHER_MAP = {
    "pubmed": fetch_pubmed,
    "biorxiv": fetch_biorxiv,
    "arxiv": fetch_arxiv,
}


def fetch_all_papers() -> list[dict[str, Any]]:
    """Run all configured search queries and return deduplicated papers."""
    all_papers: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for i, sq in enumerate(config.SEARCH_QUERIES):
        source = sq["source"]
        query = sq["query"]
        fetcher = FETCHER_MAP.get(source)
        if fetcher is None:
            logger.warning("Unknown source: %s", source)
            continue

        logger.info("[%d/%d] Fetching from %s: %s", i + 1, len(config.SEARCH_QUERIES), source, query[:80])
        papers = fetcher(query)
        logger.info("  -> Got %d papers", len(papers))

        for p in papers:
            pid = _normalize_id(p["id"])
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                p["id"] = pid
                all_papers.append(p)

        # Respect API rate limits
        time.sleep(0.5)

    logger.info("Total unique papers fetched: %d", len(all_papers))
    return all_papers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _xml_text(el: ET.Element | None) -> str:
    """Get all text content from an XML element, including mixed content."""
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def _clean_text(text: str) -> str:
    """Normalize whitespace in text."""
    return re.sub(r"\s+", " ", text).strip()


def _normalize_id(paper_id: str) -> str:
    """Normalize paper ID for deduplication."""
    pid = paper_id.strip().lower()
    # Remove common DOI prefixes
    pid = pid.replace("https://doi.org/", "").replace("http://doi.org/", "")
    return pid
