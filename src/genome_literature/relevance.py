"""Relevance scoring: is a paper about the 3D genome, and does it use AI/ML?

Every fetched record is scored before it may enter the database:

* ``genome_score`` -- weighted 3D-genome evidence (core + context terms minus
  negative terms such as genome-assembly scaffolding or protein contact maps).
  A paper must contain at least one *core* term and reach
  ``config.MIN_GENOME_SCORE``.
* ``ml_score`` -- deep-learning / machine-learning evidence.
* ``track`` -- "ml", "computational" or "experimental".
* ``relevance`` -- 0-100 ranking score (60 % 3D-genome evidence, 40 % AI/ML).
* ``dl_methods`` / ``tools`` -- architecture families and named tools found.
"""

from __future__ import annotations

from typing import Any, Iterable

from . import config
from .matching import LabeledTerms, TermSet, compile_term, normalize_text

_CORE = TermSet(config.GENOME_CORE_TERMS)
_CONTEXT = TermSet(config.GENOME_CONTEXT_TERMS)
_NEGATIVE = TermSet(config.NEGATIVE_TERMS)
_DL = TermSet(config.DL_TERMS)
_ML = TermSet(config.ML_TERMS)
_COMP = TermSet(config.COMPUTATIONAL_TERMS)
_METHODS = LabeledTerms(config.DL_METHODS)
_TOOLS = LabeledTerms(config.GENOME_TOOLS)
_EXCLUDE_TITLE = compile_term(config.EXCLUDE_TITLE_PATTERN)


def score_paper(paper: dict[str, Any]) -> dict[str, Any]:
    title = normalize_text(paper.get("title", ""))
    abstract = normalize_text(paper.get("abstract", ""))
    keywords = normalize_text(" ; ".join(paper.get("keywords") or []))
    body = f"{abstract} {keywords}".strip()
    full = f"{title} {body}"

    core, core_hits = _CORE.score(title, body)
    context, _ = _CONTEXT.score(title, body)
    negative, negative_hits = _NEGATIVE.score(title, body)
    dl, _ = _DL.score(title, body)
    ml, _ = _ML.score(title, body)
    comp, _ = _COMP.score(title, body)

    genome_score = round(max(core + context - negative, 0.0), 2)
    ml_score = round(dl + ml, 2)

    if dl >= 3 or ml >= 4:
        track = "ml"
    elif ml >= 2 or comp >= 2:
        track = "computational"
    else:
        track = "experimental"

    relevance = round(min(genome_score, 15.0) / 15.0 * 60 + min(ml_score, 12.0) / 12.0 * 40)

    return {
        "genome_score": genome_score,
        "ml_score": ml_score,
        "core_hits": core_hits,
        "negative_hits": negative_hits,
        "track": track,
        "relevance": int(relevance),
        "dl_methods": _METHODS.find(full),
        "tools": _TOOLS.find(full),
        "excluded_title": bool(_EXCLUDE_TITLE.search(title)),
    }


def annotate(paper: dict[str, Any]) -> dict[str, Any]:
    """Attach relevance fields to ``paper`` in place and return it."""
    s = score_paper(paper)
    paper["genome_score"] = s["genome_score"]
    paper["ml_score"] = s["ml_score"]
    paper["track"] = s["track"]
    paper["relevance"] = max(s["relevance"], 90) if paper.get("curated") and s["core_hits"] else s["relevance"]
    paper["dl_methods"] = s["dl_methods"]
    paper["tools"] = s["tools"]
    paper["_core_hits"] = s["core_hits"]
    paper["_excluded_title"] = s["excluded_title"]
    return paper


def is_relevant(paper: dict[str, Any]) -> bool:
    if "_core_hits" not in paper:
        annotate(paper)
    if paper.get("_excluded_title") or not paper.get("title"):
        return False
    if not paper.get("_core_hits"):
        return False
    if paper.get("curated"):
        return True
    return float(paper.get("genome_score", 0)) >= config.MIN_GENOME_SCORE


def strip_private(paper: dict[str, Any]) -> dict[str, Any]:
    for key in [k for k in paper if k.startswith("_")]:
        paper.pop(key, None)
    return paper


def filter_relevant(papers: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for p in papers:
        annotate(p)
        (kept if is_relevant(p) else rejected).append(p)
    for p in kept + rejected:
        strip_private(p)
    return kept, rejected


def track_label(track: str) -> str:
    return config.TRACKS.get(track, track)
