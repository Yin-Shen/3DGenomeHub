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

from . import __version__, assistant, config, llm, notes, retrieval, translator
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
        console.print("[red]未配置 AI 接口：请在网页“AI 设置”中填写，或在 .env 中设置 LLM_API_KEY（LLM_API_BASE、LLM_MODEL 可选）。[/]")
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
    console.print(f"Translating with {config.LLM_MODEL} @ {config.LLM_API_BASE} …")
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


def _print_events(events) -> dict:
    """Stream assistant events to the terminal; returns the final ``done`` event (or ``{}``)."""
    final: dict = {}
    thinking = False
    for event in events:
        kind = event["type"]
        if kind == "status":
            console.print(f"[dim]{event['message']}[/]")
        elif kind == "meta" and event.get("basis"):
            console.print(f"[dim]依据：{event['basis']}[/]")
        elif kind == "reasoning" and not thinking:
            thinking = True
            console.print("[dim]深度思考中…[/]")
        elif kind == "delta":
            sys.stdout.write(event["text"])
            sys.stdout.flush()
        elif kind == "error":
            console.print(f"\n[red]{event['message']}[/]")
            raise typer.Exit(1)
        elif kind == "done":
            final = event
    print()
    for warning in final.get("warnings") or []:
        console.print(f"[yellow]{warning}[/]")
    if final.get("references"):
        console.print("\n[bold]参考文献[/]")
        for ref in final["references"]:
            console.print(notes.format_reference(ref), highlight=False)
    return final


def _require_ai() -> None:
    if not llm.is_configured():
        console.print("[red]未配置 AI 接口：请在网页“设置 AI”中填写，或在 .env 中设置 LLM_API_KEY（DeepSeek 等）。[/]")
        raise typer.Exit(1)


@app.command(name="ai")
def ai_cmd(
    task: str = typer.Argument(..., help="interpret | summary | compare | review | gaps | ask"),
    query: str = typer.Option("", "--query", "-q", help="Select papers by keyword relevance (BM25) to this text"),
    ids: Optional[list[str]] = typer.Option(None, "--id", help="Paper id (repeatable)"),
    topic: str = typer.Option("", "--topic", help="Only papers in this topic (exact name, see `stats`)"),
    ml_only: bool = typer.Option(False, "--ml", help="Only AI/ML papers"),
    limit: int = typer.Option(30, "--limit", "-n", help="Maximum number of papers"),
    question: str = typer.Option("", "--question", help="Focus or question for the task"),
    deep: bool = typer.Option(False, "--deep", help="Use the reasoning model (e.g. deepseek-reasoner)"),
    no_fulltext: bool = typer.Option(False, "--no-fulltext", help="Do not fetch open-access full text"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Also write the Markdown note here"),
) -> None:
    """AI reading assistant: interpret a paper, summarize / compare many, write a review or find research gaps."""
    _setup_logging(False)
    logging.getLogger().setLevel(logging.WARNING)
    _require_ai()
    if task not in assistant.TASKS:
        console.print(f"[red]Unknown task {task!r}; choose from {', '.join(assistant.TASKS)}[/]")
        raise typer.Exit(1)
    papers = _require_papers()
    if ids:
        by_id = {p["id"]: p for p in papers}
        selected = [by_id[i] for i in ids if i in by_id]
    else:
        pool = [p for p in papers if (not topic or topic in (p.get("categories") or []))
                and (not ml_only or p.get("track") == "ml")]
        if query:
            selected = retrieval.search(pool, query, k=limit)
        else:
            selected = sorted(pool, key=lambda p: (p.get("relevance") or 0, p.get("citations") or 0), reverse=True)[:limit]
    if not selected:
        console.print("[yellow]No papers selected.[/]")
        raise typer.Exit(1)
    console.print(f"[bold]{assistant.TASKS[task]}[/] · {len(selected)} 篇文献 · 模型 {llm.model_for(deep)}")
    for i, p in enumerate(selected[:10], 1):
        console.print(f"  [{i}] {p.get('title', '')[:100]} ({p.get('year') or 'n.d.'})", highlight=False)
    if len(selected) > 10:
        console.print(f"  … 共 {len(selected)} 篇")
    final = _print_events(assistant.run_task(task, selected, question=question, deep=deep,
                                             use_fulltext=not no_fulltext))
    note = final.get("note")
    if note:
        path = config.AI_NOTES_DIR / note["file"]
        console.print(f"\n[green]已保存：{path}[/]")
        if output:
            output.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            console.print(f"[green]已写入：{output}[/]")


@app.command()
def ask(
    question: str = typer.Argument(..., help="Question about the literature (Chinese or English)"),
    deep: bool = typer.Option(False, "--deep", help="Use the reasoning model"),
) -> None:
    """Ask a question; relevant papers are retrieved from the local database and cited."""
    _setup_logging(False)
    logging.getLogger().setLevel(logging.WARNING)
    _require_ai()
    papers = _require_papers()
    _print_events(assistant.chat([{"role": "user", "content": question}], [], scope="library",
                                 library=papers, deep=deep))


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
