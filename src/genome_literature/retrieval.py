"""BM25 ranking over the local paper database (used to answer questions about the whole library)."""

from __future__ import annotations

import math
import re
import threading
from collections import Counter, defaultdict
from typing import Any, Iterable

from .matching import normalize_text

_WORD = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")
_CJK_RUN = re.compile(r"[一-鿿]+")
STOPWORDS = set("""
a an and are as at be been but by can could did do does for from had has have how in into is it its
may more most not of on or our such than that the their them these they this those through to under
using via was we were what when where which while who why will with within without would
also between both each here however novel new study studies show shows shown paper propose proposed
approach approaches method methods result results based use used data analysis
""".split())

K1 = 1.2
B = 0.75
FIELD_WEIGHTS = (("title", 3), ("tags", 2), ("abstract", 1))


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    text = normalize_text(text or "").lower()
    out: list[str] = []
    for word in _WORD.findall(text):
        if "-" in word:
            out.append(_stem(word.replace("-", "")))
            out.extend(_stem(p) for p in word.split("-") if len(p) > 1 and p not in STOPWORDS)
        elif word not in STOPWORDS and (len(word) > 1 or word.isdigit()):
            out.append(_stem(word))
    for run in _CJK_RUN.findall(text):
        out.extend(run[i:i + 2] for i in range(max(1, len(run) - 1)))
    return out


def _doc_tokens(p: dict[str, Any]) -> Counter:
    fields = {
        "title": " ".join([p.get("title") or "", p.get("title_zh") or ""]),
        "tags": " ".join((p.get("categories") or []) + (p.get("dl_methods") or []) + (p.get("tools") or [])
                         + (p.get("keywords") or [])),
        "abstract": p.get("abstract") or "",
    }
    counts: Counter = Counter()
    for name, weight in FIELD_WEIGHTS:
        for tok in tokenize(fields[name]):
            counts[tok] += weight
    return counts


class BM25Index:
    def __init__(self, papers: list[dict[str, Any]]):
        self.papers = papers
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.lengths: list[int] = []
        for i, p in enumerate(papers):
            counts = _doc_tokens(p)
            self.lengths.append(sum(counts.values()))
            for tok, tf in counts.items():
                self.postings[tok].append((i, tf))
        self.avg_len = (sum(self.lengths) / len(self.lengths)) if self.lengths else 1.0

    def idf(self, tok: str) -> float:
        n = len(self.postings.get(tok, ()))
        return math.log(1 + (len(self.papers) - n + 0.5) / (n + 0.5))

    def search(self, query_tokens: Iterable[str], k: int = 20, allowed: set[str] | None = None) -> list[tuple[float, dict[str, Any]]]:
        weights = Counter(query_tokens)
        scores: dict[int, float] = defaultdict(float)
        matched: dict[int, int] = defaultdict(int)
        for tok, qw in weights.items():
            idf = self.idf(tok)
            for i, tf in self.postings.get(tok, ()):
                norm = tf + K1 * (1 - B + B * self.lengths[i] / self.avg_len)
                scores[i] += idf * tf * (K1 + 1) / norm * (1 + 0.3 * (qw - 1))
                matched[i] += 1
        ranked = []
        for i, score in scores.items():
            paper = self.papers[i]
            if allowed is not None and paper.get("id") not in allowed:
                continue
            coverage = matched[i] / max(1, len(weights))
            ranked.append((score * (0.6 + 0.4 * coverage) + (paper.get("relevance") or 0) / 500, paper))
        ranked.sort(key=lambda x: -x[0])
        return ranked[:k]


_index_lock = threading.Lock()
_index_cache: dict[str, Any] = {"key": None, "index": None}


def get_index(papers: list[dict[str, Any]]) -> BM25Index:
    key = (id(papers), len(papers), papers[0].get("id") if papers else None, papers[-1].get("id") if papers else None)
    with _index_lock:
        if _index_cache["key"] != key:
            _index_cache["index"] = BM25Index(papers)
            _index_cache["key"] = key
        return _index_cache["index"]


def search(papers: list[dict[str, Any]], query: str | Iterable[str], k: int = 20,
           allowed: set[str] | None = None) -> list[dict[str, Any]]:
    tokens = tokenize(query) if isinstance(query, str) else [t for q in query for t in tokenize(q)]
    if not tokens:
        return []
    return [p for _, p in get_index(papers).search(tokens, k=k, allowed=allowed)]
