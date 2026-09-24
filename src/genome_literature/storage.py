"""Persistent storage: paper database (JSON), run state and curated DOI list."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

from . import config
from .records import PaperIndex, normalize_record, today

logger = logging.getLogger(__name__)


def load_papers(path: Path | None = None) -> list[dict[str, Any]]:
    """Load and normalize papers (older database rows are upgraded in memory)."""
    path = path or config.PAPERS_JSON
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        logger.exception("Failed to load papers from %s", path)
        return []
    if isinstance(data, dict):
        data = data.get("papers", [])
    if not isinstance(data, list):
        logger.warning("Unexpected data format in %s", path)
        return []
    return [normalize_record(p) for p in data if isinstance(p, dict)]


def save_papers(papers: list[dict[str, Any]], path: Path | None = None) -> None:
    """Atomically write papers, newest first, for stable and readable diffs."""
    path = path or config.PAPERS_JSON
    ordered = sorted(papers, key=lambda p: (p.get("date") or "", p.get("id") or ""), reverse=True)
    _atomic_write_json(path, ordered)
    logger.info("Saved %d papers to %s", len(ordered), path)


def load_state() -> dict[str, Any]:
    path = config.STATE_JSON
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to read %s", path)
        return {}


def save_state(state: dict[str, Any]) -> None:
    _atomic_write_json(config.STATE_JSON, state)


def load_curated_dois(path: Path | None = None) -> list[str]:
    """Read ``papers/curated_dois.txt``: one DOI per line, optional note after whitespace."""
    path = path or config.CURATED_DOIS_FILE
    if not path.exists():
        return []
    dois = []
    for line in path.read_text(encoding="utf-8").splitlines():
        token = line.strip().split()[0] if line.strip() else ""
        if token.lower().startswith("10."):
            dois.append(token.lower())
    return dois


def merge_papers(
    existing: list[dict[str, Any]],
    new_papers: Iterable[dict[str, Any]],
    first_seen: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Merge ``new_papers`` into ``existing`` (deduplicating across DOI/PMID/arXiv/title).

    Existing records keep their ``id`` and ``first_seen`` but gain metadata
    (abstracts, citations, published-version DOI, extra sources).  Returns
    ``(merged_all, actually_new)``.
    """
    first_seen = first_seen or today()
    index = PaperIndex()
    for p in existing:
        p.setdefault("first_seen", (p.get("fetched_at") or first_seen)[:10])
        index.add(p)
    actually_new: list[dict[str, Any]] = []
    fetched = 0
    for p in new_papers:
        fetched += 1
        stored, was_new = index.add(p)
        if was_new:
            stored["first_seen"] = first_seen
            actually_new.append(stored)
    logger.info(
        "Merged: %d existing + %d fetched = %d total (%d new)",
        len(existing), fetched, len(index.papers), len(actually_new),
    )
    return index.papers, actually_new


def load_json(path: Path, default: Any) -> Any:
    """Read a JSON file, returning ``default`` when it is missing or unreadable."""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to read %s", path)
        return default


def save_json(path: Path, data: Any) -> None:
    _atomic_write_json(path, data)


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
