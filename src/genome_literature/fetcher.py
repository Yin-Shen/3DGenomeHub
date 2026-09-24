"""Fetch candidate papers from PubMed, Europe PMC, bioRxiv, arXiv, Semantic Scholar and CrossRef.

Each ``fetch_*`` function returns normalized records (see ``records``).  They
do not judge relevance; the pipeline scores and filters every record after
fetching.  ``since``/``until`` (YYYY-MM-DD) restrict results to a publication
window for incremental updates; without them the searches are
relevance-ranked backfills.
"""

from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

import httpx

from . import config
from .matching import TermSet, normalize_text
from .net import HttpClient, get_client
from .records import clean_text, deduplicate, new_record, normalize_arxiv_id, normalize_doi, today

logger = logging.getLogger(__name__)

Record = dict[str, Any]
Progress = Callable[[str], None]

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
EUROPEPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EUROPEPMC_SEARCH_POST = "https://www.ebi.ac.uk/europepmc/webservices/rest/searchPOST"
BIORXIV_DETAILS = "https://api.biorxiv.org/details/biorxiv"
ARXIV_API = "https://export.arxiv.org/api/query"
SEMANTIC_SCHOLAR_SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"
CROSSREF_WORKS = "https://api.crossref.org/works"

ARXIV_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
SEASONS = {"spring": 3, "summer": 6, "fall": 9, "autumn": 9, "winter": 12}

_CORE_TERMS = TermSet(config.GENOME_CORE_TERMS)


# ---------------------------------------------------------------------------
# Query builders
# ---------------------------------------------------------------------------

_NO_PLURAL_ENDINGS = ("s", "ing", "al", "ed", "ic", "ive", "ar", "y")


def _pluralizable(term: str) -> bool:
    last = term.split()[-1].split("-")[-1]
    return (
        len(last) >= 4 and last.isalpha() and not last.isupper()
        and not last.lower().endswith(_NO_PLURAL_ENDINGS)
    )


def term_variants(term: str) -> list[str]:
    """Singular + plural forms for engines without stemming inside phrases."""
    return [term, f"{term}s"] if _pluralizable(term) else [term]


def build_pubmed_query(groups: list[list[str]]) -> str:
    def tiab(t: str) -> str:
        return f'"{t}*"[tiab]' if _pluralizable(t) else f'"{t}"[tiab]'
    return " AND ".join("(" + " OR ".join(tiab(t) for t in g) + ")" for g in groups)


def build_europepmc_query(groups: list[list[str]]) -> str:
    clauses = []
    for g in groups:
        variants = [v for t in g for v in term_variants(t)]
        clauses.append("(" + " OR ".join(f'TITLE:"{v}" OR ABSTRACT:"{v}"' for v in variants) + ")")
    return " AND ".join(clauses)


def build_arxiv_query(groups: list[list[str]], max_terms: int = 10) -> str:
    clauses = []
    for g in groups:
        variants = [v for t in g[:max_terms] for v in term_variants(t)]
        clauses.append("(" + " OR ".join(f'ti:"{v}" OR abs:"{v}"' for v in variants) + ")")
    return " AND ".join(clauses)


# ---------------------------------------------------------------------------
# PubMed (NCBI E-utilities)
# ---------------------------------------------------------------------------

def _ncbi_params() -> dict[str, str]:
    params = {"tool": "3DGenomeHub"}
    if config.NCBI_EMAIL:
        params["email"] = config.NCBI_EMAIL
    if config.NCBI_API_KEY:
        params["api_key"] = config.NCBI_API_KEY
    return params


def fetch_pubmed(
    query: str,
    max_results: int = 200,
    since: str | None = None,
    until: str | None = None,
    client: HttpClient | None = None,
) -> list[Record]:
    client = client or get_client()
    params = {
        "db": "pubmed", "term": query, "retmax": str(max_results), "retmode": "json",
        "sort": "relevance", **_ncbi_params(),
    }
    if since:
        params.update(datetype="edat", mindate=since.replace("-", "/"), maxdate=(until or today()).replace("-", "/"))
    data = _json(client.get(f"{EUTILS}/esearch.fcgi", params=params))
    ids = data.get("esearchresult", {}).get("idlist", [])
    papers: list[Record] = []
    for start in range(0, len(ids), 200):
        batch = ids[start:start + 200]
        resp = client.post(
            f"{EUTILS}/efetch.fcgi",
            data={"db": "pubmed", "id": ",".join(batch), "retmode": "xml", **_ncbi_params()},
        )
        papers.extend(parse_pubmed_xml(resp.content))
    return papers


def parse_pubmed_xml(xml: bytes | str) -> list[Record]:
    root = ET.fromstring(xml)
    out = []
    for el in root.findall(".//PubmedArticle"):
        try:
            rec = parse_pubmed_article(el)
        except Exception:
            logger.exception("Failed to parse a PubMed article")
            rec = None
        if rec:
            out.append(rec)
    return out


def parse_pubmed_article(el: ET.Element) -> Record | None:
    medline = el.find("MedlineCitation")
    if medline is None:
        return None
    art = medline.find("Article")
    if art is None:
        return None
    pmid = (medline.findtext("PMID") or "").strip()
    title = _xml_text(art.find("ArticleTitle")) or _xml_text(art.find("VernacularTitle"))
    if not title:
        return None

    parts = []
    for at in art.findall("Abstract/AbstractText"):
        text = _xml_text(at)
        label = at.get("Label")
        if text:
            parts.append(f"{label.capitalize()}: {text}" if label and label.upper() != "UNLABELLED" else text)
    abstract = " ".join(parts)

    authors = []
    for a in art.findall("AuthorList/Author"):
        last = a.findtext("LastName") or ""
        fore = a.findtext("ForeName") or a.findtext("Initials") or ""
        collective = a.findtext("CollectiveName") or ""
        name = f"{last} {fore}".strip() or collective.strip()
        if name:
            authors.append(name)

    journal = art.findtext("Journal/Title") or medline.findtext("MedlineJournalInfo/MedlineTA") or ""
    date = _pubmed_date(art, el)

    doi = pmcid = ""
    for aid in el.findall("PubmedData/ArticleIdList/ArticleId"):
        kind = aid.get("IdType")
        if kind == "doi" and not doi:
            doi = aid.text or ""
        elif kind == "pmc" and not pmcid:
            pmcid = aid.text or ""
    if not doi:
        for loc in art.findall("ELocationID"):
            if loc.get("EIdType") == "doi":
                doi = loc.text or ""
                break

    pub_types = [pt.text or "" for pt in art.findall("PublicationTypeList/PublicationType")]
    keywords = [_xml_text(k) for k in medline.findall("KeywordList/Keyword")]
    return new_record(
        "pubmed",
        title=title, abstract=abstract, authors=authors, journal=journal,
        date=date, year=date[:4] if date else None, doi=doi, pmid=pmid, pmcid=pmcid,
        publication_types=pub_types, keywords=keywords,
        is_preprint=any(t.lower() == "preprint" for t in pub_types),
    )


def _pubmed_date(art: ET.Element, el: ET.Element) -> str:
    """Electronic date, else issue date; an issue date in the future falls back to the PubMed entry date."""
    date = _pubmed_issue_date(art)
    hist = el.find("PubmedData/History/PubMedPubDate[@PubStatus='pubmed']")
    entry = _ymd(hist.findtext("Year"), hist.findtext("Month"), hist.findtext("Day")) if hist is not None else ""
    if entry and (not date or date > today()):
        return entry
    return date


def _pubmed_issue_date(art: ET.Element) -> str:
    ad = art.find("ArticleDate")
    if ad is not None and ad.findtext("Year"):
        return _ymd(ad.findtext("Year"), ad.findtext("Month"), ad.findtext("Day"))
    pd = art.find("Journal/JournalIssue/PubDate")
    if pd is not None:
        if pd.findtext("Year"):
            return _ymd(pd.findtext("Year"), pd.findtext("Month") or pd.findtext("Season"), pd.findtext("Day"))
        medline_date = pd.findtext("MedlineDate") or ""
        tokens = medline_date.replace("-", " ").split()
        if tokens and tokens[0][:4].isdigit():
            return _ymd(tokens[0][:4], tokens[1] if len(tokens) > 1 else None, None)
    return ""


def _ymd(year: str | None, month: str | None, day: str | None) -> str:
    if not year or not year.strip()[:4].isdigit():
        return ""
    m = 1
    if month:
        token = month.strip().lower()
        if token.isdigit():
            m = int(token)
        else:
            m = MONTHS.get(token[:3]) or SEASONS.get(token, 1)
    d = int(day) if day and day.strip().isdigit() else 1
    return f"{int(year.strip()[:4]):04d}-{min(max(m, 1), 12):02d}-{min(max(d, 1), 31):02d}"


# ---------------------------------------------------------------------------
# Europe PMC (journals + preprints incl. bioRxiv/medRxiv)
# ---------------------------------------------------------------------------

def fetch_europepmc(
    query: str,
    max_results: int = 200,
    since: str | None = None,
    until: str | None = None,
    client: HttpClient | None = None,
    restrict_sources: bool = True,
) -> list[Record]:
    client = client or get_client()
    q = f"({query})"
    if restrict_sources:
        q += " AND (SRC:MED OR SRC:PMC OR SRC:PPR)"
    if since:
        q += f" AND (FIRST_PDATE:[{since} TO {until or today()}])"
    papers: list[Record] = []
    cursor = "*"
    while len(papers) < max_results:
        params = {
            "query": q, "format": "json", "resultType": "core",
            "pageSize": str(min(1000, max_results - len(papers))), "cursorMark": cursor,
        }
        data = _europepmc_request(client, params)
        results = (data.get("resultList") or {}).get("result") or []
        for item in results:
            rec = parse_europepmc_item(item)
            if rec:
                papers.append(rec)
        nxt = data.get("nextCursorMark")
        if not results or not nxt or nxt == cursor:
            break
        cursor = nxt
    return papers[:max_results]


def _europepmc_request(client: HttpClient, params: dict[str, str]) -> dict[str, Any]:
    """Long boolean queries go through searchPOST; fall back to GET if unavailable."""
    if len(params["query"]) > 1500:
        try:
            return client.post(EUROPEPMC_SEARCH_POST, data=params).json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in (404, 405, 415):
                raise
            logger.warning("Europe PMC searchPOST unavailable (HTTP %d); using GET", exc.response.status_code)
    return client.get(EUROPEPMC_SEARCH, params=params).json()


def parse_europepmc_item(item: dict[str, Any]) -> Record | None:
    title = item.get("title") or ""
    if not title:
        return None
    src = item.get("source") or ""
    authors = []
    for a in (item.get("authorList") or {}).get("author") or []:
        name = a.get("fullName") or " ".join(x for x in (a.get("lastName"), a.get("initials")) if x)
        if not name and a.get("collectiveName"):
            name = a["collectiveName"]
        if name:
            authors.append(name)
    if not authors and item.get("authorString"):
        authors = [a.strip() for a in item["authorString"].rstrip(".").split(",") if a.strip()]

    journal_info = item.get("journalInfo") or {}
    journal = (journal_info.get("journal") or {}).get("title") or item.get("journalTitle") or ""
    is_preprint = src == "PPR"
    if is_preprint and not journal:
        publisher = (item.get("bookOrReportDetails") or {}).get("publisher") or ""
        journal = f"{publisher} (preprint)" if publisher else "Preprint"

    date = (item.get("firstPublicationDate") or item.get("electronicPublicationDate")
            or journal_info.get("printPublicationDate") or "")
    pdf_url = ""
    for ft in (item.get("fullTextUrlList") or {}).get("fullTextUrl") or []:
        if ft.get("documentStyle") == "pdf" and ft.get("availabilityCode") in ("OA", "F", "S"):
            pdf_url = ft.get("url", "")
            break
    ext_id = item.get("id") or ""
    return new_record(
        "europepmc",
        title=title, abstract=item.get("abstractText") or "", authors=authors, journal=journal,
        date=date, year=item.get("pubYear"), doi=item.get("doi") or "", pmid=item.get("pmid") or "",
        pmcid=item.get("pmcid") or "", epmc_id=f"{src}:{ext_id}" if ext_id else "",
        url=f"https://europepmc.org/article/{src}/{ext_id}" if (ext_id and not item.get("doi")) else "",
        pdf_url=pdf_url,
        publication_types=(item.get("pubTypeList") or {}).get("pubType") or [],
        keywords=(item.get("keywordList") or {}).get("keyword") or [],
        citations=item.get("citedByCount") or 0,
        is_preprint=is_preprint,
    )


def fetch_by_dois(dois: Iterable[str], client: HttpClient | None = None) -> list[Record]:
    """Resolve DOIs (curated landmark papers) via Europe PMC, falling back to CrossRef."""
    client = client or get_client()
    wanted = [d for d in (normalize_doi(x) for x in dois) if d]
    found: dict[str, Record] = {}
    for start in range(0, len(wanted), 10):
        batch = wanted[start:start + 10]
        query = " OR ".join(f'DOI:"{d}"' for d in batch)
        try:
            for rec in fetch_europepmc(query, max_results=50, client=client, restrict_sources=False):
                if rec["doi"] in batch and rec["doi"] not in found:
                    found[rec["doi"]] = rec
        except Exception:
            logger.exception("Europe PMC DOI lookup failed")
    for doi in wanted:
        if doi in found:
            continue
        try:
            data = client.get(f"{CROSSREF_WORKS}/{doi}", params=_crossref_params()).json()
            rec = parse_crossref_item(data.get("message") or {})
            if rec:
                found[doi] = rec
        except Exception:
            logger.warning("Could not resolve curated DOI %s", doi)
    for rec in found.values():
        rec["curated"] = True
    return list(found.values())


# ---------------------------------------------------------------------------
# bioRxiv (full scan of a recent date window, pre-filtered on 3D-genome terms)
# ---------------------------------------------------------------------------

def fetch_biorxiv_recent(
    since: str,
    until: str | None = None,
    max_records: int = config.BIORXIV_MAX_RECORDS,
    client: HttpClient | None = None,
) -> list[Record]:
    client = client or get_client()
    until = until or today()
    latest: dict[str, tuple[int, Record]] = {}
    cursor = 0
    while cursor < max_records:
        data = _json(client.get(f"{BIORXIV_DETAILS}/{since}/{until}/{cursor}/json"))
        messages = data.get("messages") or [{}]
        collection = data.get("collection") or []
        if not collection:
            break
        for item in collection:
            rec = parse_biorxiv_item(item)
            if rec is None:
                continue
            try:
                version = int(item.get("version") or 1)
            except ValueError:
                version = 1
            if rec["doi"] not in latest or version > latest[rec["doi"]][0]:
                latest[rec["doi"]] = (version, rec)
        msg = messages[0] if messages else {}
        try:
            total = int(msg.get("total") or 0)
            count = int(msg.get("count") or len(collection))
        except (TypeError, ValueError):
            total, count = 0, len(collection)
        cursor += count or len(collection)
        if total and cursor >= total:
            break
    return [rec for _, rec in latest.values()]


def parse_biorxiv_item(item: dict[str, Any]) -> Record | None:
    category = (item.get("category") or "").strip().lower()
    if category and category not in config.BIORXIV_CATEGORIES:
        return None
    title = item.get("title") or ""
    abstract = item.get("abstract") or ""
    if not title or not _CORE_TERMS.any(normalize_text(f"{clean_text(title)} {clean_text(abstract)}")):
        return None
    doi = item.get("doi") or ""
    if doi and not doi.startswith("10."):
        doi = f"10.1101/{doi}"
    authors = [a.strip() for a in (item.get("authors") or "").split(";") if a.strip()]
    server = (item.get("server") or "bioRxiv").strip() or "bioRxiv"
    return new_record(
        "biorxiv",
        title=title, abstract=abstract, authors=authors, journal=f"{server} (preprint)",
        date=item.get("date") or "", doi=doi, keywords=[category] if category else [],
        pdf_url=f"https://www.biorxiv.org/content/{doi}v{item.get('version') or 1}.full.pdf" if doi else "",
        is_preprint=True,
    )


# ---------------------------------------------------------------------------
# arXiv
# ---------------------------------------------------------------------------

def fetch_arxiv(
    query: str,
    max_results: int = 100,
    since: str | None = None,
    until: str | None = None,
    client: HttpClient | None = None,
) -> list[Record]:
    client = client or get_client()
    q = query
    if since:
        start_s = since.replace("-", "")
        end_s = (until or today()).replace("-", "")
        q = f"({q}) AND submittedDate:[{start_s}0000 TO {end_s}2359]"
    papers: list[Record] = []
    start = 0
    page = min(100, max_results)
    while start < max_results:
        params = {
            "search_query": q, "start": str(start), "max_results": str(page),
            "sortBy": "relevance", "sortOrder": "descending",
        }
        resp = client.get(ARXIV_API, params=params)
        entries = parse_arxiv_feed(resp.content)
        papers.extend(entries)
        if len(entries) < page:
            break
        start += page
    return papers[:max_results]


def parse_arxiv_feed(xml: bytes | str) -> list[Record]:
    root = ET.fromstring(xml)
    out = []
    for entry in root.findall("atom:entry", ARXIV_NS):
        id_url = (entry.findtext("atom:id", "", ARXIV_NS) or "").strip()
        if "/api/errors" in id_url:
            logger.warning("arXiv query error: %s", entry.findtext("atom:summary", "", ARXIV_NS))
            continue
        arxiv_id = id_url.split("/abs/")[-1] if "/abs/" in id_url else id_url.rsplit("/", 1)[-1]
        title = entry.findtext("atom:title", "", ARXIV_NS)
        if not title:
            continue
        authors = [
            (a.findtext("atom:name", "", ARXIV_NS) or "").strip()
            for a in entry.findall("atom:author", ARXIV_NS)
        ]
        published = entry.findtext("atom:published", "", ARXIV_NS) or ""
        journal_ref = clean_text(entry.findtext("arxiv:journal_ref", "", ARXIV_NS))
        doi = entry.findtext("arxiv:doi", "", ARXIV_NS) or ""
        pdf_url = ""
        for link in entry.findall("atom:link", ARXIV_NS):
            if link.get("title") == "pdf":
                pdf_url = link.get("href", "")
            elif link.get("title") == "doi" and not doi:
                doi = link.get("href", "")
        categories = [c.get("term", "") for c in entry.findall("atom:category", ARXIV_NS)]
        out.append(new_record(
            "arxiv",
            title=title, abstract=entry.findtext("atom:summary", "", ARXIV_NS), authors=authors,
            journal=journal_ref or "arXiv (preprint)", date=published[:10], arxiv_id=arxiv_id,
            doi=doi, url=f"https://arxiv.org/abs/{normalize_arxiv_id(arxiv_id)}",
            pdf_url=pdf_url.replace("http://", "https://"), keywords=[c for c in categories if c],
            is_preprint=not journal_ref,
        ))
    return out


# ---------------------------------------------------------------------------
# Semantic Scholar
# ---------------------------------------------------------------------------

S2_FIELDS = ("title,abstract,authors,year,venue,publicationDate,externalIds,citationCount,"
             "publicationTypes,journal,openAccessPdf,url")


def fetch_semantic_scholar(
    query: str,
    max_results: int = 100,
    since: str | None = None,
    until: str | None = None,
    client: HttpClient | None = None,
) -> list[Record]:
    client = client or get_client()
    headers = {"x-api-key": config.SEMANTIC_SCHOLAR_API_KEY} if config.SEMANTIC_SCHOLAR_API_KEY else {}
    papers: list[Record] = []
    offset = 0
    while offset < max_results:
        limit = min(100, max_results - offset)
        params = {"query": query, "limit": str(limit), "offset": str(offset), "fields": S2_FIELDS}
        if since:
            params["publicationDateOrYear"] = f"{since}:{until or today()}"
        try:
            data = client.get(SEMANTIC_SCHOLAR_SEARCH, params=params, headers=headers).json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 400 or "publicationDateOrYear" not in params:
                raise
            params.pop("publicationDateOrYear")
            data = client.get(SEMANTIC_SCHOLAR_SEARCH, params=params, headers=headers).json()
        items = data.get("data") or []
        for item in items:
            rec = parse_semantic_scholar_item(item)
            if rec and _in_window(rec, since, until):
                papers.append(rec)
        if not items or data.get("next") is None:
            break
        offset = int(data["next"])
    return papers


def parse_semantic_scholar_item(item: dict[str, Any]) -> Record | None:
    title = item.get("title") or ""
    if not title:
        return None
    ext = item.get("externalIds") or {}
    venue = ((item.get("journal") or {}).get("name") or item.get("venue") or "").strip()
    arxiv_id = ext.get("ArXiv") or ""
    if venue.lower() in ("arxiv", "arxiv.org") or (not venue and arxiv_id):
        venue = "arXiv (preprint)"
    elif venue.lower() in ("biorxiv", "medrxiv"):
        venue = f"{venue} (preprint)"
    return new_record(
        "semantic_scholar",
        title=title, abstract=item.get("abstract") or "",
        authors=[a.get("name", "") for a in item.get("authors") or []],
        journal=venue, date=item.get("publicationDate") or "", year=item.get("year"),
        doi=ext.get("DOI") or "", pmid=str(ext.get("PubMed") or ""), arxiv_id=arxiv_id,
        pmcid=f"PMC{ext['PubMedCentral']}" if ext.get("PubMedCentral") else "",
        s2_id=item.get("paperId") or "",
        url="" if (ext.get("DOI") or arxiv_id or ext.get("PubMed")) else (item.get("url") or ""),
        pdf_url=(item.get("openAccessPdf") or {}).get("url") or "",
        publication_types=item.get("publicationTypes") or [],
        citations=item.get("citationCount") or 0,
    )


# ---------------------------------------------------------------------------
# CrossRef
# ---------------------------------------------------------------------------

CROSSREF_SELECT = ("DOI,title,author,abstract,container-title,issued,published-online,"
                   "published-print,posted,URL,type,is-referenced-by-count")


def _crossref_params() -> dict[str, str]:
    return {"mailto": config.CROSSREF_MAILTO} if config.CROSSREF_MAILTO else {}


def fetch_crossref(
    query: str,
    max_results: int = 40,
    since: str | None = None,
    until: str | None = None,
    client: HttpClient | None = None,
) -> list[Record]:
    client = client or get_client()
    filters = ["type:journal-article", "type:posted-content"]
    if since:
        filters += [f"from-pub-date:{since}", f"until-pub-date:{until or today()}"]
    params = {
        "query": query, "rows": str(min(max_results, 100)), "select": CROSSREF_SELECT,
        "filter": ",".join(filters), **_crossref_params(),
    }
    try:
        data = client.get(CROSSREF_WORKS, params=params).json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 400:
            raise
        params.pop("select")
        data = client.get(CROSSREF_WORKS, params=params).json()
    papers = []
    for item in (data.get("message") or {}).get("items") or []:
        rec = parse_crossref_item(item)
        if rec:
            papers.append(rec)
    return papers


def parse_crossref_item(item: dict[str, Any]) -> Record | None:
    titles = item.get("title") or []
    title = titles[0] if titles else ""
    if not title or not item.get("DOI"):
        return None
    authors = []
    for a in item.get("author") or []:
        name = " ".join(x for x in (a.get("family"), a.get("given")) if x) or a.get("name", "")
        if name:
            authors.append(name)
    date = ""
    for key in ("published-online", "published-print", "posted", "issued", "published"):
        parts = ((item.get(key) or {}).get("date-parts") or [[]])[0]
        if parts and parts[0]:
            date = "-".join(f"{int(x):02d}" if i else str(x) for i, x in enumerate(parts))
            break
    containers = item.get("container-title") or []
    is_preprint = item.get("type") == "posted-content"
    journal = containers[0] if containers else ("Preprint" if is_preprint else "")
    return new_record(
        "crossref",
        title=title, abstract=item.get("abstract") or "", authors=authors, journal=journal,
        date=date, doi=item["DOI"], citations=item.get("is-referenced-by-count") or 0,
        is_preprint=is_preprint,
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def build_jobs(
    sources: Iterable[str],
    since: str | None,
    until: str,
    backfill: bool,
    client: HttpClient,
) -> list[tuple[str, str, Callable[[], list[Record]]]]:
    caps = config.BACKFILL_MAX_RESULTS_PER_QUERY if backfill else config.MAX_RESULTS_PER_QUERY
    enabled = set(sources)
    jobs: list[tuple[str, str, Callable[[], list[Record]]]] = []

    def add(source: str, label: str, fn: Callable[[], list[Record]]) -> None:
        if source in enabled:
            jobs.append((source, label, fn))

    for topic in config.SEARCH_TOPICS:
        groups = topic["groups"]
        name = topic["name"]
        pq, eq, aq = build_pubmed_query(groups), build_europepmc_query(groups), build_arxiv_query(groups)
        add("pubmed", name, lambda q=pq: fetch_pubmed(q, caps["pubmed"], since, until, client))
        add("europepmc", name, lambda q=eq: fetch_europepmc(q, caps["europepmc"], since, until, client))
        add("arxiv", name, lambda q=aq: fetch_arxiv(q, caps["arxiv"], since, until, client))
        for i, plain in enumerate(topic.get("plain", [])):
            add("semantic_scholar", plain,
                lambda q=plain: fetch_semantic_scholar(q, caps["semantic_scholar"], since, until, client))
            if i == 0:
                add("crossref", plain, lambda q=plain: fetch_crossref(q, caps["crossref"], since, until, client))

    biorxiv_since = since or (
        datetime.now(timezone.utc) - timedelta(days=config.BIORXIV_BACKFILL_DAYS)).strftime("%Y-%m-%d")
    add("biorxiv", f"full scan {biorxiv_since}..{until}",
        lambda: fetch_biorxiv_recent(biorxiv_since, until, client=client))
    return jobs


def fetch_all_papers(
    since: str | None = None,
    until: str | None = None,
    sources: Iterable[str] | None = None,
    backfill: bool | None = None,
    curated_dois: Iterable[str] = (),
    progress: Progress | None = None,
    report: dict[str, Any] | None = None,
    client: HttpClient | None = None,
) -> list[Record]:
    """Run every configured search and return deduplicated candidate records.

    ``report`` (if given) is filled with per-source counts and errors.
    """
    client = client or get_client()
    until = until or today()
    backfill = since is None if backfill is None else backfill
    sources = list(sources or config.ENABLED_SOURCES)
    jobs = build_jobs(sources, since, until, backfill, client)
    curated = [d for d in curated_dois if d]
    if curated:
        jobs.insert(0, ("curated", f"{len(curated)} landmark DOIs", lambda: fetch_by_dois(curated, client)))

    report = report if report is not None else {}
    report.setdefault("by_source", {})
    report.setdefault("errors", [])
    report.setdefault("skipped", {})
    collected: list[Record] = []
    consecutive_failures: dict[str, int] = {}
    for i, (source, label, fn) in enumerate(jobs, 1):
        if consecutive_failures.get(source, 0) >= config.SOURCE_FAILURE_LIMIT:
            report["skipped"][source] = report["skipped"].get(source, 0) + 1
            continue
        msg = f"[{i}/{len(jobs)}] {source}: {label[:90]}"
        logger.info(msg)
        if progress:
            progress(msg)
        try:
            papers = fn()
        except Exception as exc:
            logger.error("  -> %s failed: %s", source, exc)
            report["errors"].append({"source": source, "query": label, "error": str(exc)[:300]})
            consecutive_failures[source] = consecutive_failures.get(source, 0) + 1
            if consecutive_failures[source] == config.SOURCE_FAILURE_LIMIT:
                logger.warning("  %s failed %d times in a row; skipping its remaining queries this run",
                               source, config.SOURCE_FAILURE_LIMIT)
            continue
        consecutive_failures[source] = 0
        logger.info("  -> %d records", len(papers))
        report["by_source"][source] = report["by_source"].get(source, 0) + len(papers)
        collected.extend(papers)
    for source, n in report["skipped"].items():
        logger.warning("Skipped %d %s queries after repeated failures", n, source)

    unique = deduplicate(collected)
    report["fetched_records"] = len(collected)
    report["unique_records"] = len(unique)
    logger.info("Fetched %d records, %d unique after deduplication", len(collected), len(unique))
    return unique


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json(resp: httpx.Response) -> Any:
    """Decode JSON (tolerating raw control characters, which E-utilities emits),
    reporting what was returned instead when it is not JSON."""
    try:
        return json.loads(resp.text, strict=False)
    except ValueError as exc:
        snippet = " ".join(resp.text[:160].split())
        raise ValueError(
            f"non-JSON response from {resp.url.host} (HTTP {resp.status_code}, "
            f"{resp.headers.get('content-type', 'no content-type')}): {snippet!r}"
        ) from exc


def _in_window(rec: Record, since: str | None, until: str | None) -> bool:
    if not since or not rec.get("date"):
        return True
    return since <= rec["date"] <= (until or today())


def _xml_text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return normalize_text("".join(el.itertext()))
