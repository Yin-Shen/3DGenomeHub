"""Assign research categories using weighted, word-boundary keyword scoring.

Title hits count double.  A paper receives up to
``config.MAX_CATEGORIES_PER_PAPER`` categories whose score reaches
``config.MIN_CATEGORY_SCORE`` and ``config.CATEGORY_RELATIVE_CUTOFF`` of the
best-scoring category; otherwise it falls back to ``config.FALLBACK_CATEGORY``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from . import config
from .matching import TermSet, normalize_text

logger = logging.getLogger(__name__)

FACET_MIN_SCORE = 3.0

_CATEGORY_TERMS: dict[str, TermSet] = {
    name: TermSet(info["terms"]) for name, info in config.CATEGORIES.items()
}
_ABSTRACT_TERMS: dict[str, TermSet] = {
    name: TermSet(info["abstract_terms"]) for name, info in config.CATEGORIES.items() if info.get("abstract_terms")
}


def score_categories(paper: dict[str, Any]) -> dict[str, float]:
    title = normalize_text(paper.get("title", ""))
    abstract = normalize_text(paper.get("abstract", ""))
    keywords = normalize_text(" ; ".join(paper.get("keywords") or []))
    body = f"{abstract} {keywords}".strip()
    pub_types = {t.lower() for t in paper.get("publication_types") or []}

    scores: dict[str, float] = {}
    for name, info in config.CATEGORIES.items():
        terms = _CATEGORY_TERMS[name]
        if info.get("title_only"):
            score, _ = terms.score(title, "", title_weight=1.0)
        else:
            score, _ = terms.score(title, body)
        if name in _ABSTRACT_TERMS:
            score += _ABSTRACT_TERMS[name].score("", abstract)[0]
        if pub_types & set(info.get("pub_types", [])):
            score += 3
        if score > 0:
            scores[name] = score
    return scores


def categorize_paper(paper: dict[str, Any]) -> list[str]:
    """Up to MAX_CATEGORIES_PER_PAPER topics, plus facet categories (article type) that pass on their own."""
    scores = score_categories(paper)
    facets = [name for name, score in scores.items()
              if config.CATEGORIES[name].get("facet") and score >= FACET_MIN_SCORE]
    topical = {name: score for name, score in scores.items() if not config.CATEGORIES[name].get("facet")}
    chosen: list[str] = []
    if topical:
        ranked = sorted(topical.items(), key=lambda kv: (-kv[1], list(config.CATEGORIES).index(kv[0])))
        cutoff = max(config.MIN_CATEGORY_SCORE, ranked[0][1] * config.CATEGORY_RELATIVE_CUTOFF)
        chosen = [name for name, score in ranked if score >= cutoff][: config.MAX_CATEGORIES_PER_PAPER]
    return (chosen or [config.FALLBACK_CATEGORY]) + facets


def categorize_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Categorize all papers in place and return the list."""
    for paper in papers:
        paper["categories"] = categorize_paper(paper)
    logger.info("Categorized %d papers", len(papers))
    return papers


def category_order() -> list[str]:
    return list(config.CATEGORIES) + [config.FALLBACK_CATEGORY]


def sort_key_newest(paper: dict[str, Any]) -> tuple:
    return (paper.get("date") or "", paper.get("relevance", 0))


def group_by_category(papers: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group papers by category (a paper may appear in several groups).

    Categories follow configured order; papers inside a group are newest first.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for paper in papers:
        for cat in paper.get("categories") or [config.FALLBACK_CATEGORY]:
            groups.setdefault(cat, []).append(paper)
    for cat in groups:
        groups[cat].sort(key=sort_key_newest, reverse=True)
    order = category_order()
    ordered = {cat: groups[cat] for cat in order if cat in groups}
    for cat in sorted(groups):
        ordered.setdefault(cat, groups[cat])
    return ordered


def get_statistics(papers: list[dict[str, Any]]) -> dict[str, Any]:
    """Summary statistics for a paper collection."""
    by_year: dict[int, int] = {}
    by_source: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_track: dict[str, int] = {}
    by_method: dict[str, int] = {}
    preprints = 0
    for paper in papers:
        year = paper.get("year") or 0
        if year:
            by_year[year] = by_year.get(year, 0) + 1
        for source in paper.get("sources") or [paper.get("source", "unknown")]:
            by_source[source] = by_source.get(source, 0) + 1
        for cat in paper.get("categories") or []:
            by_category[cat] = by_category.get(cat, 0) + 1
        track = paper.get("track") or "experimental"
        by_track[track] = by_track.get(track, 0) + 1
        for method in paper.get("dl_methods") or []:
            by_method[method] = by_method.get(method, 0) + 1
        preprints += 1 if paper.get("is_preprint") else 0

    current_year = datetime.now().year
    return {
        "total_papers": len(papers),
        "ml_papers": by_track.get("ml", 0),
        "preprints": preprints,
        "recent_papers": sum(c for y, c in by_year.items() if y >= current_year - 1),
        "by_year": dict(sorted(by_year.items(), reverse=True)),
        "by_source": dict(sorted(by_source.items(), key=lambda kv: -kv[1])),
        "by_category": dict(sorted(by_category.items(), key=lambda kv: -kv[1])),
        "by_track": {t: by_track.get(t, 0) for t in config.TRACKS},
        "by_method": dict(sorted(by_method.items(), key=lambda kv: -kv[1])),
    }
