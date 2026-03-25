"""Categorize papers into predefined topics based on title + abstract keywords."""

from __future__ import annotations

import logging
from typing import Any

from . import config

logger = logging.getLogger(__name__)


def categorize_paper(paper: dict[str, Any]) -> list[str]:
    """Assign category labels to a paper based on keyword matching.

    Matches are scored by how many category keywords appear in the paper's
    title + abstract.  A paper can belong to multiple categories.
    """
    text = f"{paper.get('title', '')} {paper.get('abstract', '')}".lower()
    matched: list[tuple[str, int]] = []

    for cat_name, cat_info in config.CATEGORIES.items():
        keywords = cat_info["keywords"]
        score = sum(1 for kw in keywords if kw in text)
        if score >= 1:
            matched.append((cat_name, score))

    # Sort by match score descending
    matched.sort(key=lambda x: x[1], reverse=True)

    # Return category names (keep top 3 to avoid over-labeling)
    categories = [name for name, _ in matched[:3]]

    # Fallback: if no category matched, label as "Other"
    if not categories:
        categories = ["Other"]

    return categories


def categorize_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Categorize all papers in the list (in-place + return)."""
    for paper in papers:
        paper["categories"] = categorize_paper(paper)
    logger.info("Categorized %d papers", len(papers))
    return papers


def group_by_category(papers: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group papers by their categories.

    A paper may appear in multiple category groups.
    Returns dict sorted by category name, papers within each sorted by date descending.
    """
    groups: dict[str, list[dict[str, Any]]] = {}

    for paper in papers:
        for cat in paper.get("categories", ["Other"]):
            groups.setdefault(cat, []).append(paper)

    # Sort papers within each category by date (newest first)
    for cat in groups:
        groups[cat].sort(key=lambda p: p.get("date", ""), reverse=True)

    # Sort categories: configured order first, then "Other" last
    category_order = list(config.CATEGORIES.keys())
    sorted_groups = {}
    for cat in category_order:
        if cat in groups:
            sorted_groups[cat] = groups[cat]
    # Add any extra categories (e.g. "Other")
    for cat in sorted(groups.keys()):
        if cat not in sorted_groups:
            sorted_groups[cat] = groups[cat]

    return sorted_groups


def get_statistics(papers: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute summary statistics for a paper collection."""
    total = len(papers)
    by_year: dict[int, int] = {}
    by_source: dict[str, int] = {}
    by_category: dict[str, int] = {}

    for paper in papers:
        year = paper.get("year", 0)
        if year:
            by_year[year] = by_year.get(year, 0) + 1

        source = paper.get("source", "unknown")
        by_source[source] = by_source.get(source, 0) + 1

        for cat in paper.get("categories", []):
            by_category[cat] = by_category.get(cat, 0) + 1

    return {
        "total_papers": total,
        "by_year": dict(sorted(by_year.items(), reverse=True)),
        "by_source": by_source,
        "by_category": dict(sorted(by_category.items(), key=lambda x: x[1], reverse=True)),
    }
