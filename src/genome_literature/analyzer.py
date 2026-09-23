"""Research-landscape analysis of the paper collection.

Uses the annotations produced by ``relevance`` and ``categorizer``
(track, dl_methods, tools, categories) to report method usage, tool
mentions, year-by-year trends, a method x topic matrix, fast-growing
topics and a plain-text summary.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from . import config

TREND_START_YEAR = 2015


def analyze_papers(papers: list[dict[str, Any]]) -> dict[str, Any]:
    if not papers:
        return {"research_summary": "No papers to analyze.", "dl_method_distribution": {}, "total_papers": 0}

    ml_papers = [p for p in papers if p.get("track") == "ml"]
    method_counts = Counter(m for p in papers for m in p.get("dl_methods") or [])
    tool_counts = Counter(t for p in papers for t in p.get("tools") or [])
    trend = _trend(papers)
    landscape = _landscape(ml_papers)
    growth = _topic_growth(papers)
    hot = _hot_topics(ml_papers)

    return {
        "research_summary": _summary(papers, ml_papers, method_counts, tool_counts, trend, growth),
        "dl_method_distribution": dict(method_counts.most_common()),
        "tool_mentions": dict(tool_counts.most_common(25)),
        "trend_analysis": trend,
        "landscape_matrix": landscape,
        "landscape_methods": [m for m, _ in method_counts.most_common(8)],
        "landscape_categories": [c for c in config.CATEGORIES if any(c in row for row in landscape.values())],
        "hot_topics": hot,
        "topic_growth": growth,
        "category_insights": {g["category"]: g["insight"] for g in growth},
        "dl_paper_count": len(ml_papers),
        "dl_ratio": round(len(ml_papers) / len(papers) * 100, 1),
        "total_papers": len(papers),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def _trend(papers: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    years: dict[int, dict[str, Any]] = {}
    for p in papers:
        y = p.get("year") or 0
        if y < TREND_START_YEAR:
            continue
        row = years.setdefault(y, {"total": 0, "ml": 0, "methods": Counter()})
        row["total"] += 1
        if p.get("track") == "ml":
            row["ml"] += 1
        row["methods"].update(p.get("dl_methods") or [])
    return {
        y: {
            "total": r["total"],
            "ml": r["ml"],
            "ml_share": round(r["ml"] / r["total"] * 100, 1) if r["total"] else 0.0,
            "top_methods": dict(r["methods"].most_common(5)),
        }
        for y, r in sorted(years.items())
    }


def _landscape(ml_papers: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    matrix: dict[str, dict[str, int]] = {}
    for p in ml_papers:
        for m in p.get("dl_methods") or []:
            row = matrix.setdefault(m, {})
            for c in p.get("categories") or []:
                row[c] = row.get(c, 0) + 1
    return matrix


def _window_counts(papers: list[dict[str, Any]], months: int = 24) -> tuple[Counter, Counter]:
    now = datetime.now()
    recent_start = (now - timedelta(days=30 * months)).strftime("%Y-%m-%d")
    prior_start = (now - timedelta(days=60 * months)).strftime("%Y-%m-%d")
    recent: Counter = Counter()
    prior: Counter = Counter()
    for p in papers:
        d = p.get("date") or ""
        for c in p.get("categories") or []:
            if d >= recent_start:
                recent[c] += 1
            elif d >= prior_start:
                prior[c] += 1
    return recent, prior


def _topic_growth(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    recent, prior = _window_counts(papers)
    totals = Counter(c for p in papers for c in p.get("categories") or [])
    rows = []
    for cat, total in totals.items():
        r, pr = recent.get(cat, 0), prior.get(cat, 0)
        growth = round((r - pr) / pr * 100) if pr else None
        if pr == 0 and r > 0:
            status = "emerging"
        elif growth is not None and growth >= 25:
            status = "growing"
        elif growth is not None and growth <= -25:
            status = "slowing"
        else:
            status = "steady"
        pct = "n/a" if growth is None else f"{growth:+d}%"
        rows.append({
            "category": cat, "total": total, "last_24_months": r, "previous_24_months": pr,
            "growth_pct": growth, "status": status,
            "insight": f"{total} papers; {r} in the last 24 months vs {pr} before ({pct}), {status}",
        })
    rows.sort(key=lambda x: (-x["last_24_months"], -x["total"]))
    return rows


def _hot_topics(ml_papers: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    start = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
    counts: Counter = Counter()
    for p in ml_papers:
        if (p.get("date") or "") < start:
            continue
        for m in p.get("dl_methods") or []:
            for c in p.get("categories") or []:
                counts[(m, c)] += 1
    return [{"topic": f"{m} for {c}", "method": m, "category": c, "count": n} for (m, c), n in counts.most_common(limit)]


def _summary(
    papers: list[dict[str, Any]],
    ml_papers: list[dict[str, Any]],
    methods: Counter,
    tools: Counter,
    trend: dict[int, dict[str, Any]],
    growth: list[dict[str, Any]],
) -> str:
    total = len(papers)
    lines = [
        "RESEARCH LANDSCAPE: 3D Genome x Deep Learning",
        "",
        f"Papers tracked: {total}",
        f"AI/ML papers:   {len(ml_papers)} ({round(len(ml_papers) / total * 100, 1)}%)",
        "",
    ]
    if methods:
        lines.append("Most used architectures:")
        peak = methods.most_common(1)[0][1]
        for m, c in methods.most_common(8):
            lines.append(f"  {m:30s} {c:5d} {'█' * max(1, round(c / peak * 25))}")
        lines.append("")
    if tools:
        lines.append("Most mentioned tools/models: " + ", ".join(f"{t} ({c})" for t, c in tools.most_common(8)))
        lines.append("")
    recent_years = [y for y in sorted(trend, reverse=True)[:4]]
    if recent_years:
        lines.append("Recent years:")
        for y in recent_years:
            r = trend[y]
            top = ", ".join(f"{m} ({c})" for m, c in r["top_methods"].items()) or "-"
            lines.append(f"  {y}: {r['total']} papers, {r['ml']} AI/ML ({r['ml_share']}%) | {top}")
        lines.append("")
    rising = [g for g in growth if g["status"] in ("growing", "emerging")][:5]
    if rising:
        lines.append("Fastest-growing topics (last 24 months vs previous 24):")
        for g in rising:
            pct = "new" if g["growth_pct"] is None else f"{g['growth_pct']:+d}%"
            lines.append(f"  - {g['category']}: {g['last_24_months']} papers ({pct})")
        lines.append("")
    complete_years = [y for y in sorted(trend) if y < datetime.now().year]
    if len(complete_years) >= 2:
        a, b = complete_years[-2], complete_years[-1]
        if trend[a]["ml"]:
            change = round((trend[b]["ml"] - trend[a]["ml"]) / trend[a]["ml"] * 100)
            lines.append(f"AI/ML papers {a} -> {b}: {trend[a]['ml']} -> {trend[b]['ml']} ({change:+d}%)")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    return "\n".join(lines)
