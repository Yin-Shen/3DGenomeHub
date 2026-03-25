"""Intelligent analysis and summarization for 3D genome × deep learning papers.

Extracts DL methods, identifies trends, generates research landscape summaries.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# Deep learning method/architecture keywords for extraction
# ---------------------------------------------------------------------------
DL_METHODS: dict[str, list[str]] = {
    "CNN": ["cnn", "convolutional neural network", "convolutional network", "conv2d", "resnet",
            "u-net", "unet", "vgg", "inception"],
    "Transformer": ["transformer", "self-attention", "multi-head attention", "attention mechanism",
                    "vision transformer", "vit"],
    "GNN": ["graph neural network", "gnn", "graph convolutional", "gcn", "graph attention",
            "gat", "message passing"],
    "GAN": ["generative adversarial", "gan", "discriminator", "generator network",
            "adversarial training", "wgan", "cyclegan", "pix2pix"],
    "Autoencoder": ["autoencoder", "vae", "variational autoencoder", "encoder-decoder",
                    "latent space", "reconstruction loss"],
    "Diffusion Model": ["diffusion model", "denoising diffusion", "ddpm", "score-based",
                        "diffusion process"],
    "RNN/LSTM": ["recurrent neural network", "rnn", "lstm", "long short-term memory", "gru",
                 "bidirectional lstm", "bi-lstm"],
    "Foundation Model": ["foundation model", "pre-trained model", "pretrained model",
                         "large language model", "llm", "bert", "gpt", "large-scale pre-training"],
    "Reinforcement Learning": ["reinforcement learning", "reward function", "policy gradient",
                               "q-learning", "rl agent"],
    "Random Forest / XGBoost": ["random forest", "xgboost", "gradient boosting", "decision tree",
                                "ensemble method", "lightgbm"],
    "SVM / Classical ML": ["support vector machine", "svm", "logistic regression", "naive bayes",
                           "k-nearest neighbor", "knn"],
    "Transfer Learning": ["transfer learning", "domain adaptation", "fine-tuning", "fine-tune",
                          "pre-training and fine-tuning"],
    "Contrastive Learning": ["contrastive learning", "self-supervised", "siamese network",
                             "triplet loss", "contrastive loss", "simclr", "byol"],
    "Sequence Model": ["sequence model", "seq2seq", "sequence-to-sequence", "dna sequence model",
                       "nucleotide-level", "base-pair resolution"],
}

# Key 3D genome tools/methods to track
GENOME_TOOLS: dict[str, list[str]] = {
    "Akita": ["akita"],
    "Enformer": ["enformer"],
    "DeepHiC": ["deephic"],
    "HiCPlus": ["hicplus", "hic-plus"],
    "HiCSR": ["hicsr", "hic-sr"],
    "HiCNN": ["hicnn"],
    "Orca": ["orca model", "orca predicts"],
    "Sei": ["sei framework", "sei model"],
    "Basenji": ["basenji"],
    "DeepLoop": ["deeploop"],
    "Peakachu": ["peakachu"],
    "DeepTAD": ["deeptad"],
    "HiCGAN": ["hicgan"],
    "scHiCluster": ["shicluster", "schic cluster"],
    "Higashi": ["higashi"],
    "SnapHiC": ["snaphic"],
    "Dip-C": ["dip-c"],
    "DeepC": ["deepc"],
    "EPCOT": ["epcot"],
    "ChromaFold": ["chromafold"],
    "C.Origami": ["c.origami", "origami model"],
    "HiCFoundation": ["hicfoundation"],
    "HiCDiffusion": ["hicdiffusion"],
}


def analyze_papers(papers: list[dict[str, Any]]) -> dict[str, Any]:
    """Perform comprehensive analysis of the paper collection.

    Returns a rich analysis dict with:
    - research_summary: text summary of the field
    - dl_method_distribution: which DL methods are most used
    - tool_mentions: which genome tools are mentioned
    - trend_analysis: year-by-year trending topics
    - landscape_matrix: DL method × genome problem matrix
    - hot_topics: currently trending research directions
    - key_findings: auto-extracted key insights
    """
    if not papers:
        return {"research_summary": "No papers to analyze.", "dl_method_distribution": {}}

    # 1. Extract DL methods from each paper
    method_counts: Counter = Counter()
    tool_counts: Counter = Counter()
    papers_with_methods: list[dict] = []

    for p in papers:
        text = f"{p.get('title', '')} {p.get('abstract', '')}".lower()
        methods = _extract_methods(text)
        tools = _extract_tools(text)
        p_copy = {**p, "_dl_methods": methods, "_tools": tools}
        papers_with_methods.append(p_copy)
        for m in methods:
            method_counts[m] += 1
        for t in tools:
            tool_counts[t] += 1

    # 2. DL relevance scoring
    dl_papers = [p for p in papers_with_methods if p["_dl_methods"]]
    dl_ratio = len(dl_papers) / len(papers) if papers else 0

    # 3. Year-by-year trend analysis
    trend = _analyze_trends(papers_with_methods)

    # 4. Research landscape matrix
    landscape = _build_landscape_matrix(papers_with_methods)

    # 5. Hot topics (recent papers)
    hot_topics = _identify_hot_topics(papers_with_methods)

    # 6. Generate text summary
    summary = _generate_summary(
        papers, dl_papers, method_counts, tool_counts, trend, hot_topics
    )

    # 7. Category insights
    cat_insights = _category_insights(papers)

    return {
        "research_summary": summary,
        "dl_method_distribution": dict(method_counts.most_common(20)),
        "tool_mentions": dict(tool_counts.most_common(20)),
        "trend_analysis": trend,
        "landscape_matrix": landscape,
        "hot_topics": hot_topics,
        "category_insights": cat_insights,
        "dl_paper_count": len(dl_papers),
        "dl_ratio": round(dl_ratio * 100, 1),
        "total_papers": len(papers),
        "generated_at": datetime.now().isoformat(),
    }


def _extract_methods(text: str) -> list[str]:
    """Extract DL method names from text."""
    found = []
    for method_name, keywords in DL_METHODS.items():
        for kw in keywords:
            if kw in text:
                found.append(method_name)
                break
    return found


def _extract_tools(text: str) -> list[str]:
    """Extract known genome tools from text."""
    found = []
    for tool_name, keywords in GENOME_TOOLS.items():
        for kw in keywords:
            if kw in text:
                found.append(tool_name)
                break
    return found


def _analyze_trends(papers: list[dict]) -> dict[str, Any]:
    """Analyze method trends by year."""
    year_methods: dict[int, Counter] = {}
    year_counts: dict[int, int] = {}

    for p in papers:
        year = p.get("year", 0)
        if not year or year < 2015:
            continue
        year_counts[year] = year_counts.get(year, 0) + 1
        if year not in year_methods:
            year_methods[year] = Counter()
        for m in p.get("_dl_methods", []):
            year_methods[year][m] += 1

    # Format for output
    trend_data = {}
    for year in sorted(year_methods.keys()):
        trend_data[year] = {
            "total": year_counts.get(year, 0),
            "top_methods": dict(year_methods[year].most_common(5)),
        }

    return trend_data


def _build_landscape_matrix(papers: list[dict]) -> dict[str, dict[str, int]]:
    """Build a matrix of DL methods × genome categories."""
    matrix: dict[str, dict[str, int]] = {}

    for p in papers:
        methods = p.get("_dl_methods", [])
        categories = p.get("categories", [])
        for m in methods:
            if m not in matrix:
                matrix[m] = {}
            for c in categories:
                matrix[m][c] = matrix[m].get(c, 0) + 1

    return matrix


def _identify_hot_topics(papers: list[dict]) -> list[dict[str, Any]]:
    """Identify hot research topics from recent papers."""
    # Focus on papers from last 2 years
    current_year = datetime.now().year
    recent = [p for p in papers if p.get("year", 0) >= current_year - 1]

    if not recent:
        recent = papers[:50]

    # Count method+category combinations
    topic_counts: Counter = Counter()
    for p in recent:
        methods = p.get("_dl_methods", [])
        cats = p.get("categories", [])
        for m in methods:
            for c in cats:
                topic_counts[f"{m} for {c}"] += 1

    hot = []
    for topic, count in topic_counts.most_common(10):
        hot.append({"topic": topic, "count": count})

    return hot


def _category_insights(papers: list[dict]) -> dict[str, str]:
    """Generate a one-line insight for each category."""
    from .categorizer import group_by_category

    grouped = group_by_category(papers)
    insights = {}

    for cat, cat_papers in grouped.items():
        n = len(cat_papers)
        years = [p.get("year", 0) for p in cat_papers if p.get("year")]
        if not years:
            insights[cat] = f"{n} papers"
            continue

        newest = max(years)
        oldest = min(years)

        # Count recent vs old
        current_year = datetime.now().year
        recent = sum(1 for y in years if y >= current_year - 1)

        if recent > n * 0.5:
            trend = "rapidly growing"
        elif recent > n * 0.25:
            trend = "actively researched"
        elif recent > 0:
            trend = "moderately active"
        else:
            trend = "established"

        insights[cat] = f"{n} papers ({oldest}-{newest}), {trend}, {recent} recent"

    return insights


def _generate_summary(
    all_papers: list[dict],
    dl_papers: list[dict],
    method_counts: Counter,
    tool_counts: Counter,
    trend: dict,
    hot_topics: list[dict],
) -> str:
    """Generate a comprehensive text summary of the research landscape."""
    total = len(all_papers)
    dl_count = len(dl_papers)
    current_year = datetime.now().year

    lines = []
    lines.append("=" * 60)
    lines.append("RESEARCH LANDSCAPE: 3D Genome × Deep Learning")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"Total papers tracked: {total}")
    lines.append(f"Deep learning-related: {dl_count} ({round(dl_count/total*100, 1) if total else 0}%)")
    lines.append("")

    # Top methods
    if method_counts:
        lines.append("--- Most Used DL Architectures ---")
        for method, count in method_counts.most_common(8):
            bar = "█" * min(count, 30)
            lines.append(f"  {method:25s} {count:4d} {bar}")
        lines.append("")

    # Top tools
    if tool_counts:
        lines.append("--- Most Referenced Tools ---")
        for tool, count in tool_counts.most_common(8):
            lines.append(f"  {tool:25s} {count:4d}")
        lines.append("")

    # Recent trends
    recent_years = sorted([y for y in trend if y >= current_year - 3], reverse=True)
    if recent_years:
        lines.append("--- Recent Trends ---")
        for year in recent_years:
            info = trend[year]
            top = ", ".join(f"{m}({c})" for m, c in info["top_methods"].items())
            lines.append(f"  {year}: {info['total']} papers | Top methods: {top}")
        lines.append("")

    # Hot topics
    if hot_topics:
        lines.append("--- Hot Research Directions ---")
        for ht in hot_topics[:6]:
            lines.append(f"  • {ht['topic']} ({ht['count']} papers)")
        lines.append("")

    # Key observations
    lines.append("--- Key Observations ---")
    if method_counts:
        top_method = method_counts.most_common(1)[0][0]
        lines.append(f"  • {top_method} is the most widely used architecture")
    if tool_counts:
        top_tool = tool_counts.most_common(1)[0][0]
        lines.append(f"  • {top_tool} is the most referenced tool/model")

    # Growth trend
    if len(recent_years) >= 2:
        y1, y2 = recent_years[0], recent_years[1]
        if trend[y1]["total"] > trend[y2]["total"]:
            growth = round((trend[y1]["total"] - trend[y2]["total"]) / max(trend[y2]["total"], 1) * 100)
            lines.append(f"  • {growth}% growth from {y2} to {y1}")
        elif trend[y1]["total"] < trend[y2]["total"]:
            lines.append(f"  • Publication pace slowing from {y2} to {y1}")

    lines.append("")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    return "\n".join(lines)


def compute_dl_relevance(paper: dict[str, Any]) -> float:
    """Compute a 0-1 relevance score for deep learning focus."""
    text = f"{paper.get('title', '')} {paper.get('abstract', '')}".lower()

    score = 0.0
    # Check DL method mentions
    for method_name, keywords in DL_METHODS.items():
        for kw in keywords:
            if kw in text:
                score += 0.15
                break

    # Check specific DL terms
    dl_terms = ["deep learning", "neural network", "machine learning",
                "training", "loss function", "epoch", "batch",
                "prediction", "classification", "regression",
                "model architecture", "hyperparameter"]
    for term in dl_terms:
        if term in text:
            score += 0.05

    # Check 3D genome terms
    genome_terms = ["hi-c", "chromatin", "genome", "tad", "loop",
                    "contact map", "chromosome", "3d structure"]
    genome_hits = sum(1 for t in genome_terms if t in text)
    if genome_hits >= 2:
        score += 0.1

    return min(score, 1.0)
