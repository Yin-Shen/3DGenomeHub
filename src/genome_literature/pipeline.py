"""Main pipeline: fetch -> score & filter -> deduplicate/merge -> categorize -> save -> README -> email."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Iterable

from . import config
from .categorizer import categorize_papers
from .email_notifier import send_digest_email
from .fetcher import fetch_all_papers
from .readme_generator import write_outputs
from .records import now_iso, today
from .relevance import filter_relevant
from .storage import load_curated_dois, load_papers, load_state, merge_papers, save_papers, save_state
from .summarizer import generate_digest

logger = logging.getLogger(__name__)


def resolve_window(
    state: dict[str, Any],
    has_papers: bool,
    since: str | None,
    backfill: bool,
    sources: Iterable[str],
) -> tuple[str | None, bool]:
    """Decide the publication window: (since, is_backfill)."""
    if backfill or not has_papers:
        return None, True
    if since:
        return since, False
    per_source = state.get("sources") or {}
    last_dates = [per_source.get(s, {}).get("until") for s in sources]
    if last_dates and all(last_dates):
        start = datetime.strptime(min(last_dates), "%Y-%m-%d") - timedelta(days=config.INCREMENTAL_OVERLAP_DAYS)
    elif state.get("last_fetch_until"):
        start = datetime.strptime(state["last_fetch_until"], "%Y-%m-%d") - timedelta(days=config.INCREMENTAL_OVERLAP_DAYS)
    else:
        start = datetime.strptime(today(), "%Y-%m-%d") - timedelta(days=config.DEFAULT_LOOKBACK_DAYS)
    return start.strftime("%Y-%m-%d"), False


def refresh_annotations(papers: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Re-score and re-categorize every paper; drop ones that no longer qualify."""
    kept, pruned = filter_relevant(papers)
    categorize_papers(kept)
    return kept, pruned


def run_pipeline(
    skip_fetch: bool = False,
    skip_email: bool = False,
    skip_readme: bool = False,
    since: str | None = None,
    backfill: bool = False,
    sources: Iterable[str] | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Execute the update pipeline and return a summary dict."""
    run_date = today()
    sources = list(sources or config.ENABLED_SOURCES)
    result: dict[str, Any] = {"success": False, "run_date": run_date}

    def step(msg: str) -> None:
        logger.info(msg)
        if progress:
            progress(msg)

    state = load_state()
    existing = load_papers()
    result["existing_count"] = len(existing)
    step(f"Loaded {len(existing)} papers from the database")

    fetched: list[dict[str, Any]] = []
    report: dict[str, Any] = {}
    if skip_fetch:
        step("Skipping fetch")
    else:
        window_since, is_backfill = resolve_window(state, bool(existing), since, backfill, sources)
        result["mode"] = "backfill" if is_backfill else "incremental"
        result["since"] = window_since
        known = {p.get("doi") for p in existing} | {p.get("preprint_doi") for p in existing}
        curated = [d for d in load_curated_dois() if d not in known]
        step(f"Fetching ({result['mode']}, since {window_since or 'all time'}) from: {', '.join(sources)}")
        fetched = fetch_all_papers(
            since=window_since, until=run_date, sources=sources, backfill=is_backfill,
            curated_dois=curated, progress=progress, report=report,
        )
    result["fetched_count"] = len(fetched)
    result["fetch_errors"] = report.get("errors", [])
    result["by_source"] = report.get("by_source", {})

    kept, rejected = filter_relevant(fetched)
    result["relevant_count"] = len(kept)
    result["rejected_count"] = len(rejected)
    step(f"Relevance filter: kept {len(kept)} of {len(fetched)} candidates")

    merged, new_papers = merge_papers(existing, kept, first_seen=run_date)
    all_papers, pruned = refresh_annotations(merged)
    live_ids = {p["id"] for p in all_papers}
    new_papers = [p for p in new_papers if p["id"] in live_ids]
    result.update(total_count=len(all_papers), new_count=len(new_papers), pruned_count=len(pruned))
    if pruned:
        step(f"Pruned {len(pruned)} stored papers that no longer pass the relevance filter")

    save_papers(all_papers)

    if not skip_fetch:
        failed = {e["source"] for e in report.get("errors", [])}
        per_source = state.setdefault("sources", {})
        for s in sources:
            if s not in failed:
                per_source.setdefault(s, {})["until"] = run_date
        if not failed or failed != set(sources):
            state["last_fetch_until"] = run_date
    state["last_run"] = now_iso()
    state["last_new_ids"] = [p["id"] for p in new_papers]
    runs = state.setdefault("runs", [])
    runs.append({
        "date": run_date,
        "mode": result.get("mode", "no-fetch"),
        "since": result.get("since"),
        "fetched": result["fetched_count"],
        "relevant": result["relevant_count"],
        "new": result["new_count"],
        "total": result["total_count"],
        "errors": len(result["fetch_errors"]),
    })
    state["runs"] = runs[-30:]
    save_state(state)

    digest = generate_digest(new_papers, all_papers)
    result["digest_summary"] = digest["summary_text"]

    if skip_readme:
        step("Skipping README update")
    else:
        written = write_outputs(all_papers, new_papers)
        step(f"README.md and {len(written) - 1} category pages updated")

    if skip_email:
        step("Skipping email")
    else:
        result["email_sent"] = send_digest_email(new_papers, digest)

    result["success"] = True
    step(
        f"Done: {result['new_count']} new, {result['total_count']} total"
        + (f", {len(result['fetch_errors'])} query errors" if result["fetch_errors"] else "")
    )
    return result


def last_new_papers(papers: list[dict[str, Any]], state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Papers added by the most recent pipeline run."""
    state = load_state() if state is None else state
    ids = set(state.get("last_new_ids") or [])
    return [p for p in papers if p.get("id") in ids]
