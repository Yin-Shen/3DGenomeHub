"""Local search and export helpers shared by the CLI and the web GUI."""

from __future__ import annotations

import csv
import io
import re
from typing import Any

_TOKEN_RE = re.compile(r'"([^"]+)"|(\S+)')

CSV_FIELDS = [
    "id", "title", "authors", "journal", "year", "date", "doi", "pmid", "arxiv_id", "url", "pdf_url",
    "track", "relevance", "citations", "is_preprint", "categories", "dl_methods", "tools", "sources",
    "first_seen", "abstract",
]


def parse_query(query: str) -> list[str]:
    return [(a or b).lower() for a, b in _TOKEN_RE.findall(query or "") if (a or b).strip()]


def search_papers(papers: list[dict[str, Any]], query: str, limit: int | None = 50) -> list[dict[str, Any]]:
    """AND-search over title/abstract/authors/journal/keywords/tags; quoted phrases supported.

    Ranking: title hits x3, tag/keyword hits x2, other hits x1, plus relevance/100.
    """
    terms = parse_query(query)
    if not terms:
        return []
    scored = []
    for p in papers:
        title = (p.get("title") or "").lower()
        tags = " ".join((p.get("categories") or []) + (p.get("dl_methods") or []) + (p.get("tools") or [])
                        + (p.get("keywords") or [])).lower()
        other = " ".join([p.get("abstract") or "", " ".join(p.get("authors") or []), p.get("journal") or "",
                          p.get("doi") or ""]).lower()
        score = 0.0
        for t in terms:
            if t in title:
                score += 3
            elif t in tags:
                score += 2
            elif t in other:
                score += 1
            else:
                score = -1
                break
        if score > 0:
            scored.append((score + (p.get("relevance") or 0) / 100, p))
    scored.sort(key=lambda x: (x[0], x[1].get("date") or ""), reverse=True)
    results = [p for _, p in scored]
    return results[:limit] if limit else results


def to_csv(papers: list[dict[str, Any]]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for p in papers:
        row = dict(p)
        for key in ("authors", "categories", "dl_methods", "tools", "sources"):
            row[key] = "; ".join(p.get(key) or [])
        writer.writerow(row)
    return out.getvalue()


def _bib_escape(text: str) -> str:
    return re.sub(r"([{}%&#$_])", r"\\\1", text or "")


def bibtex_key(p: dict[str, Any], used: set[str]) -> str:
    first = (p.get("authors") or ["anon"])[0].split()[0]
    first = re.sub(r"[^A-Za-z]", "", first) or "anon"
    word = next((w for w in re.findall(r"[A-Za-z]{4,}", p.get("title") or "")), "paper")
    base = f"{first.lower()}{p.get('year') or ''}{word.lower()}"
    key, n = base, 1
    while key in used:
        n += 1
        key = f"{base}{n}"
    used.add(key)
    return key


def to_bibtex(papers: list[dict[str, Any]]) -> str:
    used: set[str] = set()
    entries = []
    for p in papers:
        kind = "misc" if p.get("is_preprint") else "article"
        fields = {
            "title": "{" + _bib_escape(p.get("title", "")) + "}",
            "author": " and ".join(_bib_escape(a) for a in p.get("authors") or []),
            "journal" if kind == "article" else "howpublished": _bib_escape(p.get("journal", "")),
            "year": str(p.get("year") or ""),
            "doi": p.get("doi") or "",
            "url": p.get("url") or "",
            "eprint": p.get("arxiv_id") or "",
            "pmid": p.get("pmid") or "",
            "keywords": _bib_escape(", ".join((p.get("categories") or []) + (p.get("dl_methods") or []))),
        }
        body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields.items() if v)
        entries.append(f"@{kind}{{{bibtex_key(p, used)},\n{body}\n}}")
    return "\n\n".join(entries) + ("\n" if entries else "")
