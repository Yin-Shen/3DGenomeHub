"""Auto-generate README.md from the paper database."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from . import config
from .categorizer import get_statistics, group_by_category

logger = logging.getLogger(__name__)


def generate_readme(papers: list[dict[str, Any]]) -> str:
    """Generate a complete README.md content from the paper collection."""
    stats = get_statistics(papers)
    grouped = group_by_category(papers)
    now = datetime.now().strftime("%Y-%m-%d")

    sections: list[str] = []

    # Header
    sections.append(_header(stats, now))

    # Table of Contents
    sections.append(_table_of_contents(grouped))

    # Statistics
    sections.append(_statistics_section(stats))

    # Papers by category
    for cat_name, cat_papers in grouped.items():
        sections.append(_category_section(cat_name, cat_papers))

    # Footer
    sections.append(_footer(now))

    return "\n\n".join(sections) + "\n"


def _header(stats: dict[str, Any], date: str) -> str:
    return f"""# 3D Genome & Deep Learning Literature Hub

> A curated, auto-updating collection of research papers at the intersection of **3D genome biology** and **deep learning / machine learning**.

![Last Updated](https://img.shields.io/badge/Last_Updated-{date}-blue)
![Papers](https://img.shields.io/badge/Papers-{stats['total_papers']}-green)
![Categories](https://img.shields.io/badge/Categories-{len(stats['by_category'])}-orange)

---

## Overview

This repository automatically tracks the latest research combining **three-dimensional genome organization** (Hi-C, chromatin conformation capture, TADs, loops, compartments) with **deep learning approaches** (CNNs, transformers, GNNs, generative models, foundation models).

**Features:**
- Automatic daily/weekly paper fetching from **PubMed**, **bioRxiv**, and **arXiv**
- Intelligent categorization into research topics
- Auto-generated README with organized paper listings
- Email digest notifications for new papers
- Full metadata including abstracts, DOIs, and direct links"""


def _table_of_contents(grouped: dict[str, list]) -> str:
    lines = ["## Table of Contents", ""]
    for cat_name in grouped:
        anchor = cat_name.lower().replace(" ", "-").replace("&", "").replace("/", "").replace("--", "-")
        count = len(grouped[cat_name])
        lines.append(f"- [{cat_name}](#{anchor}) ({count} papers)")
    lines.append(f"- [How It Works](#how-it-works)")
    lines.append(f"- [Setup & Configuration](#setup--configuration)")
    lines.append(f"- [Contributing](#contributing)")
    return "\n".join(lines)


def _statistics_section(stats: dict[str, Any]) -> str:
    lines = ["## Statistics", ""]

    # Year distribution
    lines.append("### Papers by Year")
    lines.append("| Year | Count |")
    lines.append("|------|-------|")
    for year, count in sorted(stats["by_year"].items(), reverse=True):
        bar = "█" * min(count, 50)
        lines.append(f"| {year} | {count} {bar} |")

    lines.append("")

    # Source distribution
    lines.append("### Papers by Source")
    lines.append("| Source | Count |")
    lines.append("|--------|-------|")
    for source, count in stats["by_source"].items():
        lines.append(f"| {source} | {count} |")

    return "\n".join(lines)


def _category_section(cat_name: str, papers: list[dict[str, Any]]) -> str:
    cat_info = config.CATEGORIES.get(cat_name, {})
    description = cat_info.get("description", "")

    lines = [f"## {cat_name}", ""]
    if description:
        lines.append(f"> {description}")
        lines.append("")

    lines.append(f"<details><summary>Show {len(papers)} papers</summary>")
    lines.append("")

    # Paper table
    lines.append("| # | Title | Authors | Journal | Year | Links |")
    lines.append("|---|-------|---------|---------|------|-------|")

    for i, paper in enumerate(papers, 1):
        title = _escape_md(paper["title"])
        if len(title) > 100:
            title = title[:97] + "..."

        authors = _format_authors_short(paper["authors"])
        journal = _escape_md(paper.get("journal", ""))
        year = paper.get("year", "")

        links = []
        if paper.get("url"):
            links.append(f"[Paper]({paper['url']})")
        if paper.get("doi"):
            links.append(f"[DOI](https://doi.org/{paper['doi']})")

        links_str = " / ".join(links) if links else "-"
        lines.append(f"| {i} | {title} | {authors} | {journal} | {year} | {links_str} |")

    lines.append("")
    lines.append("</details>")

    return "\n".join(lines)


def _footer(date: str) -> str:
    return f"""## How It Works

This tool automatically:

1. **Fetches** papers from PubMed (NCBI E-utilities), bioRxiv API, and arXiv API using carefully crafted search queries targeting the intersection of 3D genome biology and deep learning
2. **Categorizes** papers into research topics using keyword-based classification (Hi-C enhancement, 3D structure prediction, TAD detection, loop prediction, etc.)
3. **Deduplicates** results using DOI/ID normalization across all sources
4. **Generates** this README automatically with organized tables, statistics, and links
5. **Notifies** subscribers via email digest with new paper summaries

### Automated Pipeline

The GitHub Actions workflow runs on a configurable schedule (default: weekly) to:
- Fetch new papers from all sources
- Merge with existing database (avoiding duplicates)
- Re-categorize and regenerate README
- Send email notifications for new discoveries
- Auto-commit and push updates

## Setup & Configuration

### Quick Start

```bash
# Clone the repository
git clone https://github.com/Yin-Shen/3DGenomeHub.git
cd 3DGenomeHub

# Install dependencies
pip install -r requirements.txt

# Fetch papers and generate README
python -m genome_literature.cli fetch
python -m genome_literature.cli update-readme

# Or run the full pipeline
python -m genome_literature.cli run-pipeline
```

### Email Notifications

Configure email via environment variables or `.env` file:

```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
EMAIL_FROM=your-email@gmail.com
EMAIL_RECIPIENTS=user1@example.com,user2@example.com
```

### GitHub Actions (Automatic Updates)

The included workflow (`.github/workflows/update.yml`) runs automatically. To enable:
1. Fork this repository
2. Add secrets: `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`, `EMAIL_RECIPIENTS`
3. The workflow will run weekly and on manual dispatch

## Contributing

Contributions welcome! You can help by:
- Adding new search queries to cover more research areas
- Improving the categorization keywords
- Suggesting new features

## License

MIT License

---

*Last updated: {date} | Auto-generated by [3DGenomeHub](https://github.com/Yin-Shen/3DGenomeHub)*"""


def _format_authors_short(authors: list[str]) -> str:
    """Format author list: 'First et al.' or 'First, Second'."""
    if not authors:
        return "Unknown"
    if len(authors) == 1:
        return _escape_md(authors[0])
    if len(authors) == 2:
        return _escape_md(f"{authors[0]}, {authors[1]}")
    return _escape_md(f"{authors[0]} et al.")


def _escape_md(text: str) -> str:
    """Escape markdown special characters in table cells."""
    return text.replace("|", "\\|").replace("\n", " ")
