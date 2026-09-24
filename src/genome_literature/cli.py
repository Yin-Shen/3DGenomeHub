"""Command-line interface for the 3D Genome & Deep Learning Literature Hub."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import __version__, config, translator
from .analyzer import analyze_papers
from .categorizer import get_statistics
from .pipeline import last_new_papers, refresh_annotations, run_pipeline
from .readme_generator import write_outputs
from .relevance import track_label
from .search import search_papers, to_bibtex, to_csv
from .storage import load_papers, save_papers
from .summarizer import generate_digest, short_authors

app = typer.Typer(
    name="genome-literature",
    help="3D Genome & Deep Learning Literature Hub — auto-updating research tracker.",
    add_completion=False,
)
console = Console()


def _setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )


def _sources(value: Optional[str]) -> Optional[list[str]]:
    if not value:
        return None
    sources = [s.strip() for s in value.split(",") if s.strip()]
    unknown = [s for s in sources if s not in config.ALL_SOURCES]
    if unknown:
        raise typer.BadParameter(f"unknown source(s) {unknown}; choose from {config.ALL_SOURCES}")
    return sources


def _require_papers() -> list[dict]:
    papers = load_papers()
    if not papers:
        console.print("[red]No papers in database. Run 'run-pipeline' first.[/]")
        raise typer.Exit(1)
    return papers


def _report(result: dict) -> None:
    console.print(f"\n[bold green]Pipeline completed[/] ({result.get('mode', 'no fetch')}"
                  f"{', since ' + result['since'] if result.get('since') else ''})")
    console.print(f"  Candidates fetched: {result.get('fetched_count', 0)}")
    console.print(f"  Passed relevance:   {result.get('relevant_count', 0)}")
    console.print(f"  New papers:         {result.get('new_count', 0)}")
    console.print(f"  Pruned:             {result.get('pruned_count', 0)}")
    console.print(f"  Total in database:  {result.get('total_count', 0)}")
    errors = result.get("fetch_errors") or []
    if errors:
        console.print(f"[yellow]  {len(errors)} queries failed:[/]")
        for e in errors[:10]:
            console.print(f"    {e['source']}: {e['error'][:150]}")


def _exit_if_fetch_failed(result: dict) -> None:
    if result.get("fetch_errors") and not result.get("fetched_count"):
        console.print("[red]Every query failed — check network access to the literature APIs.[/]")
        raise typer.Exit(2)


@app.command(name="run-pipeline")
def run_pipeline_cmd(
    since: Optional[str] = typer.Option(None, help="Only fetch papers published since YYYY-MM-DD"),
    backfill: bool = typer.Option(False, "--backfill", help="Relevance-ranked search across all years"),
    sources: Optional[str] = typer.Option(None, help=f"Comma-separated subset of {config.ALL_SOURCES}"),
    skip_fetch: bool = typer.Option(False, "--skip-fetch", help="Skip paper fetching"),
    skip_email: bool = typer.Option(False, "--skip-email", help="Skip email notification"),
    skip_readme: bool = typer.Option(False, "--skip-readme", help="Skip README / topic page generation"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Fetch -> filter -> merge -> categorize -> save -> README -> email."""
    _setup_logging(verbose)
    result = run_pipeline(
        skip_fetch=skip_fetch, skip_email=skip_email, skip_readme=skip_readme,
        since=since, backfill=backfill, sources=_sources(sources),
    )
    _report(result)
    _exit_if_fetch_failed(result)


@app.command()
def fetch(
    since: Optional[str] = typer.Option(None, help="Only fetch papers published since YYYY-MM-DD"),
    backfill: bool = typer.Option(False, "--backfill", help="Relevance-ranked search across all years"),
    sources: Optional[str] = typer.Option(None, help=f"Comma-separated subset of {config.ALL_SOURCES}"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Fetch and store new papers without touching README or email."""
    _setup_logging(verbose)
    result = run_pipeline(skip_email=True, skip_readme=True, since=since, backfill=backfill, sources=_sources(sources))
    _report(result)
    _exit_if_fetch_failed(result)


@app.command()
def rebuild(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    """Re-score, deduplicate and re-categorize the stored database (after editing config.py)."""
    _setup_logging(verbose)
    papers = load_papers()
    for p in papers:
        p.setdefault("first_seen", (p.get("fetched_at") or "")[:10])
    kept, pruned = refresh_annotations(papers)
    save_papers(kept)
    write_outputs(kept, last_new_papers(kept))
    merged = len(papers) - len(kept) - len(pruned)
    console.print(f"[green]Rebuilt database: {len(kept)} papers kept, {merged} duplicates merged, "
                  f"{len(pruned)} pruned.[/]")


@app.command(name="update-readme")
def update_readme(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    """Regenerate README.md and docs/papers/*.md from the database."""
    _setup_logging(verbose)
    papers = load_papers()
    written = write_outputs(papers, last_new_papers(papers))
    console.print(f"[green]README.md and {len(written) - 1} topic pages updated ({len(papers)} papers).[/]")


@app.command()
def stats(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    """Show database statistics."""
    _setup_logging(verbose)
    papers = _require_papers()
    s = get_statistics(papers)
    console.print(f"\n[bold]{s['total_papers']} papers[/] · {s['ml_papers']} AI/ML · {s['preprints']} preprints\n")

    table = Table(title="Papers by year")
    table.add_column("Year", style="cyan")
    table.add_column("Count", justify="right", style="green")
    table.add_column("")
    peak = max(s["by_year"].values() or [1])
    for year, count in list(s["by_year"].items())[:15]:
        table.add_row(str(year), str(count), "█" * max(1, round(count / peak * 40)))
    console.print(table)

    for title, data in (("Track", {track_label(k): v for k, v in s["by_track"].items()}),
                        ("Topic", s["by_category"]), ("Architecture", s["by_method"]), ("Source", s["by_source"])):
        table = Table(title=f"Papers by {title.lower()}")
        table.add_column(title, style="cyan")
        table.add_column("Count", justify="right", style="green")
        for k, v in data.items():
            table.add_row(k, str(v))
        console.print(table)


@app.command()
def search(
    query: str = typer.Argument(..., help='Search terms (AND); quote phrases, e.g. \'"loop extrusion" polymer\''),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
    ml_only: bool = typer.Option(False, "--ml", help="Only AI/ML papers"),
) -> None:
    """Search the local database."""
    papers = _require_papers()
    if ml_only:
        papers = [p for p in papers if p.get("track") == "ml"]
    results = search_papers(papers, query, limit=limit)
    if not results:
        console.print(f"[yellow]No papers matching '{query}'[/]")
        return
    console.print(f"\n[bold]{len(results)} papers matching '{query}':[/]\n")
    for p in results:
        console.print(f"  [bold]{p['title']}[/]")
        console.print(f"  {short_authors(p.get('authors') or [])} | {p.get('journal', '')} ({p.get('date') or p.get('year')})")
        console.print(f"  {track_label(p.get('track', ''))} · relevance {p.get('relevance')} · {', '.join(p.get('categories') or [])}")
        console.print(f"  {p.get('url', '')}\n")


@app.command()
def export(
    format: str = typer.Option("json", "--format", "-f", help="json, csv or bib"),
    output: str = typer.Option("papers_export", "--output", "-o", help="Output filename (without extension)"),
    ml_only: bool = typer.Option(False, "--ml", help="Only AI/ML papers"),
) -> None:
    """Export the database to JSON, CSV or BibTeX."""
    papers = _require_papers()
    if ml_only:
        papers = [p for p in papers if p.get("track") == "ml"]
    if format == "json":
        text, ext = json.dumps(papers, ensure_ascii=False, indent=1), "json"
    elif format == "csv":
        text, ext = to_csv(papers), "csv"
    elif format in ("bib", "bibtex"):
        text, ext = to_bibtex(papers), "bib"
    else:
        console.print(f"[red]Unknown format: {format}[/]")
        raise typer.Exit(1)
    out_path = Path(f"{output}.{ext}")
    out_path.write_text(text, encoding="utf-8")
    console.print(f"[green]Exported {len(papers)} papers to {out_path}[/]")


@app.command()
def analyze() -> None:
    """Print the research-landscape summary."""
    console.print(analyze_papers(_require_papers())["research_summary"])


@app.command()
def translate(
    ml_only: bool = typer.Option(False, "--ml", help="Only AI/ML papers"),
    new_only: bool = typer.Option(False, "--new", help="Only papers added by the last update"),
    ids: Optional[list[str]] = typer.Option(None, "--id", help="Paper id (repeatable)"),
    limit: int = typer.Option(100, "--limit", "-n", help="Maximum papers to translate in this run"),
    no_limit: bool = typer.Option(False, "--all", help="Translate every selected paper"),
    force: bool = typer.Option(False, "--force", help="Re-translate even if a translation exists (reviewed entries are kept)"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Academic Chinese translation of titles and abstracts (cached in papers/translations.json)."""
    _setup_logging(verbose)
    if not translator.is_configured():
        console.print("[red]未配置翻译接口：请在 .env 中设置 TRANSLATE_API_KEY、TRANSLATE_API_BASE、TRANSLATE_MODEL。[/]")
        raise typer.Exit(1)
    papers = _require_papers()
    selected = papers
    if ids:
        wanted = set(ids)
        selected = [p for p in selected if p["id"] in wanted]
    if new_only:
        selected = last_new_papers(selected)
    if ml_only:
        selected = [p for p in selected if p.get("track") == "ml"]
    selected = sorted(selected, key=lambda p: (p.get("track") == "ml", p.get("date") or ""), reverse=True)
    console.print(f"Translating with {config.TRANSLATE_MODEL} @ {config.TRANSLATE_API_BASE} …")
    stats = translator.translate_papers(selected, force=force, limit=None if no_limit else limit)
    console.print(f"[green]Translated {stats['translated']}[/] · needs review {stats['needs_review']} · "
                  f"failed {stats['failed']} · left for later {stats['skipped_over_limit']}")
    for err in stats["errors"][:5]:
        console.print(f"  [yellow]{err}[/]")
    if stats["translated"]:
        write_outputs(papers, last_new_papers(papers))
        console.print("README.md and topic pages updated with Chinese titles.")


@app.command(name="translate-text")
def translate_text_cmd(
    title: str = typer.Argument(..., help="English title"),
    abstract: str = typer.Argument("", help="English abstract"),
) -> None:
    """Translate an arbitrary title/abstract and show the automatic checks."""
    try:
        entry = translator.translate_text(title, abstract)
    except translator.TranslationError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    console.print(f"[bold]{entry['title_zh']}[/]\n\n{entry['abstract_zh']}\n")
    if entry["issues"]:
        console.print("[yellow]自动检查发现以下问题，请人工校对：[/]")
        for issue in entry["issues"]:
            console.print(f"  - {issue}")
    else:
        console.print("[green]自动检查通过（名称/缩写、数值、术语、完整性）[/]")


@app.command(name="send-email")
def send_email_cmd(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    """Email the digest of papers added by the last update."""
    _setup_logging(verbose)
    from .email_notifier import send_digest_email

    papers = _require_papers()
    new = last_new_papers(papers)
    if not new:
        console.print("[yellow]No new papers from the last update.[/]")
        return
    if send_digest_email(new, generate_digest(new, papers)):
        console.print("[green]Email digest sent.[/]")
    else:
        console.print("[red]Failed to send email. Check SMTP configuration.[/]")
        raise typer.Exit(1)


@app.command()
def serve(
    port: int = typer.Option(config.WEB_PORT, help="Port"),
    host: str = typer.Option(config.WEB_HOST, help="Bind address"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Do not open a browser"),
) -> None:
    """Start the web GUI."""
    from .web_app import start_server

    start_server(port=port, open_browser=not no_browser, host=host)


@app.command()
def version() -> None:
    """Print the version."""
    console.print(__version__)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
