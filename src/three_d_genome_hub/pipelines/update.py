"""Automated refresh pipeline for the 3DGenomeHub knowledge base."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Iterable, List, Sequence

import httpx

from ..config import DEFAULT_DATA_FILE
from ..ingestion.loader import KnowledgeBaseRepository, ingest_bundle
from ..ingestion.schema import load_bundle
from ..models import Resource

LOGGER = logging.getLogger("three_d_genome_hub.pipeline.refresh")

CROSSREF_API = "https://api.crossref.org/works"
BIORXIV_API = "https://api.biorxiv.org/details/biorxiv"
MAX_RECORDS = 10


def _slugify(text: str, prefix: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return f"{prefix}-{slug[:40]}"


def _make_resource(
    identifier: str,
    title: str,
    url: str,
    authors: str | None,
    summary: str,
    year: int | None,
    tags: Sequence[str],
    category: str = "Research-Summaries",
    level: str = "intermediate",
) -> Resource:
    return Resource(
        id=identifier,
        title=title,
        type="article",
        level=level,
        category=category,
        summary=summary,
        tags=list(tags),
        author=authors,
        source="Automated Harvest",
        url=url,
        language="en",
        year=year,
    )


def _extract_authors(items: Iterable[dict]) -> str:
    authors = []
    for author in items:
        given = author.get("given")
        family = author.get("family")
        if given and family:
            authors.append(f"{given} {family}")
        elif family:
            authors.append(family)
    return ", ".join(authors)


def fetch_crossref_articles(query: str = "3D genome", rows: int = MAX_RECORDS) -> List[Resource]:
    params = {
        "query": query,
        "rows": rows,
        "select": "DOI,title,URL,issued,author,abstract",
        "filter": "type:journal-article,language:en",
        "sort": "published",
        "order": "desc",
    }
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(CROSSREF_API, params=params)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:  # noqa: BLE001 - runtime safety around HTTP errors
        LOGGER.warning("Crossref lookup failed: %s", exc)
        return []

    items = data.get("message", {}).get("items", [])
    resources: List[Resource] = []
    for item in items:
        title_list = item.get("title") or []
        title = title_list[0] if title_list else None
        url = item.get("URL")
        if not title or not url:
            continue
        doi = item.get("DOI") or title
        identifier = _slugify(doi, "CR")
        issued = item.get("issued", {}).get("date-parts", [])
        year = issued[0][0] if issued and issued[0] else None
        authors = _extract_authors(item.get("author", []))
        abstract = item.get("abstract") or "Recent journal article related to 3D genome research."
        summary = re.sub(r"<[^>]+>", "", abstract).strip()
        resources.append(
            _make_resource(
                identifier=identifier,
                title=title,
                url=url,
                authors=authors or None,
                summary=summary,
                year=year,
                tags=["Journal", "Crossref", "3D Genome"],
            )
        )
    return resources


def fetch_biorxiv_preprints(query: str = "3D genome", max_results: int = MAX_RECORDS) -> List[Resource]:
    params = {
        "category": "genomics",
        "page": 0,
    }
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(f"{BIORXIV_API}/{query.replace(' ', '%20')}/0", params=params)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("bioRxiv lookup failed: %s", exc)
        return []

    collection = data.get("collection", [])[:max_results]
    resources: List[Resource] = []
    for item in collection:
        title = item.get("title")
        url = item.get("rel_doi") or item.get("url")
        if not title or not url:
            continue
        identifier = _slugify(item.get("doi", title), "BX")
        authors = item.get("authors")
        summary = item.get("abstract") or "bioRxiv preprint highlighting emerging ideas in spatial genomics."
        try:
            year = datetime.fromisoformat(item.get("date", "")).year if item.get("date") else None
        except ValueError:
            year = None
        resources.append(
            _make_resource(
                identifier=identifier,
                title=title,
                url=url,
                authors=authors,
                summary=summary,
                year=year,
                tags=["Preprint", "bioRxiv", "3D Genome"],
            )
        )
    return resources


def refresh_knowledge_base(
    repository: KnowledgeBaseRepository,
    curated_data_path: str | None = None,
    search_terms: Sequence[str] = ("3D genome", "chromatin architecture"),
) -> int:
    """Refresh the SQLite store with curated and programmatically fetched entries."""

    curated_path = curated_data_path or DEFAULT_DATA_FILE
    curated_bundle = load_bundle(curated_path)
    resources: dict[str, Resource] = {resource.id: resource for resource in curated_bundle.resources}

    for term in search_terms:
        for resource in fetch_crossref_articles(term):
            resources[resource.id] = resource
        for resource in fetch_biorxiv_preprints(term):
            resources[resource.id] = resource

    bundle = curated_bundle.copy(deep=True)
    bundle.resources = list(resources.values())
    ingest_bundle(bundle, repository)
    return len(bundle.resources)


__all__ = ["fetch_crossref_articles", "fetch_biorxiv_preprints", "refresh_knowledge_base"]
