"""Summarize and organize papers — generate human-readable digests."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from .categorizer import get_statistics, group_by_category

logger = logging.getLogger(__name__)


def generate_digest(
    new_papers: list[dict[str, Any]],
    all_papers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate a structured digest of new and all papers.

    Returns a dict with:
      - summary_text: human-readable summary
      - new_papers_by_category: grouped new papers
      - statistics: overall stats
      - generated_at: timestamp
    """
    stats = get_statistics(all_papers)
    new_grouped = group_by_category(new_papers)
    new_stats = get_statistics(new_papers)

    summary_lines = [
        f"3D Genome & Deep Learning Literature Update",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}",
        f"",
        f"Total papers in database: {stats['total_papers']}",
        f"New papers in this update: {new_stats['total_papers']}",
        f"",
    ]

    if new_papers:
        summary_lines.append("New Papers by Category:")
        for cat, papers in new_grouped.items():
            summary_lines.append(f"  - {cat}: {len(papers)} paper(s)")
        summary_lines.append("")

        summary_lines.append("Highlights (most recent new papers):")
        # Pick top 5 newest papers
        sorted_new = sorted(new_papers, key=lambda p: p.get("date", ""), reverse=True)
        for p in sorted_new[:5]:
            authors_short = p["authors"][0] if p["authors"] else "Unknown"
            if len(p["authors"]) > 1:
                authors_short += " et al."
            summary_lines.append(f"  * [{p['year']}] {p['title']}")
            summary_lines.append(f"    {authors_short} | {p['journal']}")
    else:
        summary_lines.append("No new papers found in this update.")

    return {
        "summary_text": "\n".join(summary_lines),
        "new_papers_by_category": new_grouped,
        "all_papers_by_category": group_by_category(all_papers),
        "statistics": stats,
        "new_statistics": new_stats,
        "generated_at": datetime.now().isoformat(),
    }


def format_paper_entry(paper: dict[str, Any], index: int = 0) -> str:
    """Format a single paper as a readable text entry."""
    authors_str = ", ".join(paper["authors"][:3])
    if len(paper["authors"]) > 3:
        authors_str += " et al."

    lines = [
        f"{index}. **{paper['title']}**",
        f"   {authors_str}",
        f"   *{paper['journal']}* ({paper['year']})",
    ]
    if paper.get("doi"):
        lines.append(f"   DOI: {paper['doi']}")
    if paper.get("abstract"):
        # Truncate abstract to ~200 chars for digest
        abstract = paper["abstract"]
        if len(abstract) > 200:
            abstract = abstract[:197] + "..."
        lines.append(f"   > {abstract}")

    return "\n".join(lines)
