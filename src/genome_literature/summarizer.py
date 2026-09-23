"""Human-readable digests of new papers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .categorizer import get_statistics, group_by_category
from .relevance import track_label


def rank_key(paper: dict[str, Any]) -> tuple:
    """AI/ML papers first, then relevance, then recency."""
    return (paper.get("track") == "ml", paper.get("relevance", 0), paper.get("date") or "")


def short_authors(authors: list[str], limit: int = 1) -> str:
    if not authors:
        return "Unknown authors"
    if len(authors) <= limit + 1:
        return ", ".join(authors)
    return ", ".join(authors[:limit]) + " et al."


def generate_digest(
    new_papers: list[dict[str, Any]],
    all_papers: list[dict[str, Any]],
    highlights: int = 8,
) -> dict[str, Any]:
    stats = get_statistics(all_papers)
    new_stats = get_statistics(new_papers)
    new_grouped = group_by_category(new_papers)
    ranked = sorted(new_papers, key=rank_key, reverse=True)

    lines = [
        "3D Genome & Deep Learning Literature Update",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        f"Papers in database: {stats['total_papers']} ({stats['ml_papers']} AI/ML)",
        f"New in this update: {new_stats['total_papers']} ({new_stats['ml_papers']} AI/ML)",
        "",
    ]
    if new_papers:
        lines.append("New papers by category:")
        for cat, papers in new_grouped.items():
            lines.append(f"  - {cat}: {len(papers)}")
        lines.append("")
        lines.append("Highlights:")
        for p in ranked[:highlights]:
            lines.append(f"  * {p['title']}")
            lines.append(
                f"    {short_authors(p.get('authors') or [])} | {p.get('journal') or 'n/a'} "
                f"({p.get('date') or p.get('year')}) | {track_label(p.get('track', ''))}"
            )
    else:
        lines.append("No new papers in this update.")

    return {
        "summary_text": "\n".join(lines),
        "new_papers": ranked,
        "new_papers_by_category": new_grouped,
        "statistics": stats,
        "new_statistics": new_stats,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
