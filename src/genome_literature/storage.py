"""Persistent storage for the paper database (JSON-based)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from . import config

logger = logging.getLogger(__name__)


def load_papers(path: Path | None = None) -> list[dict[str, Any]]:
    """Load papers from a JSON file."""
    path = path or config.PAPERS_JSON
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        logger.warning("Unexpected data format in %s", path)
        return []
    except Exception:
        logger.exception("Failed to load papers from %s", path)
        return []


def save_papers(papers: list[dict[str, Any]], path: Path | None = None) -> None:
    """Save papers to a JSON file."""
    path = path or config.PAPERS_JSON
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(papers, f, ensure_ascii=False, indent=2)
    logger.info("Saved %d papers to %s", len(papers), path)


def merge_papers(
    existing: list[dict[str, Any]],
    new_papers: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Merge new papers into existing collection, deduplicating by ID.

    Returns (merged_all, actually_new) where actually_new contains only
    papers that were not already in the existing collection.
    """
    seen_ids: set[str] = set()
    merged: list[dict[str, Any]] = []

    # Add existing papers first
    for p in existing:
        pid = p.get("id", "").strip().lower()
        if pid and pid not in seen_ids:
            seen_ids.add(pid)
            merged.append(p)

    # Add new papers, tracking which are truly new
    actually_new: list[dict[str, Any]] = []
    for p in new_papers:
        pid = p.get("id", "").strip().lower()
        if pid and pid not in seen_ids:
            seen_ids.add(pid)
            merged.append(p)
            actually_new.append(p)

    logger.info(
        "Merged: %d existing + %d fetched = %d total (%d new)",
        len(existing), len(new_papers), len(merged), len(actually_new),
    )
    return merged, actually_new
