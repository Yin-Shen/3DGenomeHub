"""Command-line interface for 3D Genome & Deep Learning Literature Hub."""

from __future__ import annotations

import json
import logging
import sys

import typer
from rich.console import Console
from rich.table import Table

from . import config
from .categorizer import categorize_papers, get_statistics, group_by_category
from .fetcher import fetch_all_papers
from .pipeline import run_pipeline
from .readme_generator import generate_readme
from .storage import load_papers, merge_papers, save_papers
from .summarizer import generate_digest

app = typer.Typer(
    name="genome-literature",
    help="3D Genome & Deep Learning Literature Hub — auto-updating research tracker.",
    add_completion=False,
)
console = Console()


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
def fetch(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Fetch papers from PubMed, bioRxiv, and arXiv."""
    _setup_logging(verbose)
    console.print("[bold blue]Fetching papers from all sources...[/]")

    papers = fetch_all_papers()
    categorize_papers(papers)

    console.print(f"[green]Fetched {len(papers)} unique papers[/]")

    # Merge with existing
    existing = load_papers()
    all_papers, new_papers = merge_papers(existing, papers)
    save_papers(all_papers)

    if new_papers:
        save_papers(new_papers, config.NEW_PAPERS_JSON)
        console.print(f"[bold green]{len(new_papers)} new papers added![/]")
    else:
        console.print("[yellow]No new papers found.[/]")

    console.print(f"Total papers in database: {len(all_papers)}")


@app.command()
def update_readme(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Regenerate README.md from the paper database."""
    _setup_logging(verbose)
    papers = load_papers()
    if not papers:
        console.print("[red]No papers in database. Run 'fetch' first.[/]")
        raise typer.Exit(1)

    categorize_papers(papers)
    content = generate_readme(papers)
    config.README_PATH.write_text(content, encoding="utf-8")
    console.print(f"[green]README.md updated with {len(papers)} papers.[/]")


@app.command()
def stats(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Show statistics about the paper database."""
    _setup_logging(verbose)
    papers = load_papers()
    if not papers:
        console.print("[red]No papers in database. Run 'fetch' first.[/]")
        raise typer.Exit(1)

    categorize_papers(papers)
    s = get_statistics(papers)

    console.print(f"\n[bold]Total papers: {s['total_papers']}[/]\n")

    # Year table
    table = Table(title="Papers by Year")
    table.add_column("Year", style="cyan")
    table.add_column("Count", style="green")
    table.add_column("Bar")
    for year, count in sorted(s["by_year"].items(), reverse=True):
        bar = "█" * min(count, 60)
        table.add_row(str(year), str(count), bar)
    console.print(table)

    # Source table
    table = Table(title="Papers by Source")
    table.add_column("Source", style="cyan")
    table.add_column("Count", style="green")
    for source, count in s["by_source"].items():
        table.add_row(source, str(count))
    console.print(table)

    # Category table
    table = Table(title="Papers by Category")
    table.add_column("Category", style="cyan")
    table.add_column("Count", style="green")
    for cat, count in s["by_category"].items():
        table.add_row(cat, str(count))
    console.print(table)


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Search the local paper database by keyword."""
    _setup_logging(verbose)
    papers = load_papers()
    if not papers:
        console.print("[red]No papers in database. Run 'fetch' first.[/]")
        raise typer.Exit(1)

    terms = query.lower().split()
    results = []
    for p in papers:
        text = f"{p.get('title', '')} {p.get('abstract', '')} {' '.join(p.get('categories', []))}".lower()
        score = sum(1 for t in terms if t in text)
        if score > 0:
            results.append((score, p))

    results.sort(key=lambda x: x[0], reverse=True)
    results = results[:limit]

    if not results:
        console.print(f"[yellow]No papers matching '{query}'[/]")
        return

    console.print(f"\n[bold]Found {len(results)} papers matching '{query}':[/]\n")
    for score, p in results:
        authors = p["authors"][0] + " et al." if len(p["authors"]) > 1 else (p["authors"][0] if p["authors"] else "?")
        cats = ", ".join(p.get("categories", []))
        console.print(f"  [bold]{p['title']}[/]")
        console.print(f"  {authors} | {p.get('journal', '')} ({p.get('year', '')})")
        console.print(f"  Categories: {cats}")
        console.print(f"  {p.get('url', '')}")
        console.print()


@app.command(name="run-pipeline")
def run_pipeline_cmd(
    skip_fetch: bool = typer.Option(False, "--skip-fetch", help="Skip paper fetching"),
    skip_email: bool = typer.Option(False, "--skip-email", help="Skip email notification"),
    skip_readme: bool = typer.Option(False, "--skip-readme", help="Skip README update"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run the full pipeline: fetch → categorize → merge → README → email."""
    _setup_logging(verbose)
    console.print("[bold blue]Running full pipeline...[/]\n")

    result = run_pipeline(
        skip_fetch=skip_fetch,
        skip_email=skip_email,
        skip_readme=skip_readme,
    )

    if result["success"]:
        console.print(f"\n[bold green]Pipeline completed![/]")
        console.print(f"  Existing papers: {result.get('existing_count', 0)}")
        console.print(f"  Fetched: {result.get('fetched_count', 0)}")
        console.print(f"  New papers: {result.get('new_count', 0)}")
        console.print(f"  Total: {result.get('total_count', 0)}")
    else:
        console.print("[red]Pipeline failed. Check logs for details.[/]")
        raise typer.Exit(1)


@app.command()
def export(
    format: str = typer.Option("json", "--format", "-f", help="Export format: json, csv"),
    output: str = typer.Option("papers_export", "--output", "-o", help="Output filename (without extension)"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Export the paper database to JSON or CSV."""
    _setup_logging(verbose)
    papers = load_papers()
    if not papers:
        console.print("[red]No papers in database.[/]")
        raise typer.Exit(1)

    if format == "json":
        out_path = f"{output}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(papers, f, ensure_ascii=False, indent=2)
    elif format == "csv":
        import csv

        out_path = f"{output}.csv"
        fields = ["id", "title", "authors", "journal", "year", "date", "doi", "url", "source", "categories"]
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for p in papers:
                row = {**p}
                row["authors"] = "; ".join(p.get("authors", []))
                row["categories"] = "; ".join(p.get("categories", []))
                writer.writerow(row)
    else:
        console.print(f"[red]Unknown format: {format}[/]")
        raise typer.Exit(1)

    console.print(f"[green]Exported {len(papers)} papers to {out_path}[/]")


@app.command(name="send-email")
def send_email_cmd(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Send email digest with the latest new papers."""
    _setup_logging(verbose)
    from .email_notifier import send_digest_email

    all_papers = load_papers()
    new_papers = load_papers(config.NEW_PAPERS_JSON)

    if not new_papers:
        console.print("[yellow]No new papers to report.[/]")
        return

    categorize_papers(all_papers)
    categorize_papers(new_papers)
    digest = generate_digest(new_papers, all_papers)

    sent = send_digest_email(new_papers, digest)
    if sent:
        console.print("[green]Email digest sent successfully![/]")
    else:
        console.print("[red]Failed to send email. Check configuration.[/]")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
