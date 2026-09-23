"""Keyword matching with word boundaries, case rules and title weighting.

Term syntax (used by every vocabulary in ``config``):

* ``"deep learning"`` -- case-insensitive, whole words only, hyphen/space
  interchangeable ("deep-learning", "deeplearning"), optional plural suffix.
* ``"TAD"`` -- an all-uppercase term is an acronym and is matched
  case-sensitively ("TADs" matches, "metadata" and "tadpole" do not).
* ``"re:<regex>"`` -- a raw regular expression used verbatim (case-sensitive
  unless the pattern itself sets ``(?i)``).
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable, Mapping

_ALNUM = "A-Za-z0-9"
_DASHES = re.compile("[‐‑‒–—―−﹣－]")
_SPACES = re.compile(r"[\s   ]+")


def normalize_text(text: str | None) -> str:
    """Normalize dashes and whitespace so terms match consistently."""
    if not text:
        return ""
    return _SPACES.sub(" ", _DASHES.sub("-", text)).strip()


@lru_cache(maxsize=4096)
def compile_term(term: str) -> re.Pattern[str]:
    if term.startswith("re:"):
        return re.compile(term[3:])
    stripped = term.strip()
    case_sensitive = stripped == stripped.upper() and any(c.isalpha() for c in stripped)
    parts = [p for p in re.split(r"[\s\-]+", stripped) if p]
    body = r"[\s\-]?".join(re.escape(p) for p in parts)
    if stripped[-1].isalpha():
        body += r"(?:s|es)?"
    pattern = rf"(?<![{_ALNUM}]){body}(?![{_ALNUM}])"
    return re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)


def term_label(term: str) -> str:
    return term[3:] if term.startswith("re:") else term


class TermSet:
    """A weighted vocabulary that scores title/abstract text."""

    def __init__(self, terms: Mapping[str, float] | Iterable[str]):
        if not isinstance(terms, Mapping):
            terms = {t: 1.0 for t in terms}
        self.terms = [(label, compile_term(label), float(weight)) for label, weight in terms.items()]

    def find(self, text: str) -> list[str]:
        return [label for label, pattern, _ in self.terms if pattern.search(text)]

    def any(self, text: str) -> bool:
        return any(pattern.search(text) for _, pattern, _ in self.terms)

    def score(self, title: str, abstract: str = "", title_weight: float = 2.0) -> tuple[float, list[str]]:
        """Sum weights of matched terms; a title hit counts ``title_weight`` times."""
        total = 0.0
        hits: list[str] = []
        for label, pattern, weight in self.terms:
            if title and pattern.search(title):
                total += weight * title_weight
                hits.append(label)
            elif abstract and pattern.search(abstract):
                total += weight
                hits.append(label)
        return total, hits


class LabeledTerms:
    """Maps display labels to term lists; reports which labels occur in text."""

    def __init__(self, groups: Mapping[str, Iterable[str]]):
        self.groups = [(label, [compile_term(t) for t in terms]) for label, terms in groups.items()]

    def find(self, text: str) -> list[str]:
        return [label for label, patterns in self.groups if any(p.search(text) for p in patterns)]
