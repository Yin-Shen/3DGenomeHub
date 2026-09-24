"""Open-access full text for the AI reading assistant.

Sources, tried in order:

* Europe PMC ``fullTextXML`` (JATS) for papers with a PMCID — open-access
  articles and author manuscripts;
* arXiv HTML (``arxiv.org/html/<id>``) for arXiv preprints.

Results are cached in ``config.FULLTEXT_CACHE_DIR``; papers without an
available full text are remembered for ``FULLTEXT_CACHE_DAYS_MISSING`` days.
When nothing is available the assistant works from the abstract.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any

import httpx

from . import config
from .net import HttpClient, get_client

logger = logging.getLogger(__name__)

EUROPEPMC_FULLTEXT = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
ARXIV_HTML = "https://arxiv.org/html/{arxiv_id}"

_SKIP_TITLES = re.compile(
    r"acknowledg|author contribution|competing interest|conflict of interest|funding|additional information|"
    r"reporting summary|peer review|supplementary|ethics declaration|abbreviation|footnote|references?$|bibliography",
    re.I,
)
_PRIORITY = [
    (re.compile(r"result|finding|discussion|conclusion|summary", re.I), 1.0),
    (re.compile(r"introduction|background|overview|figure|table", re.I), 0.7),
    (re.compile(r"method|material|experimental procedure|implementation|training|dataset|data availability|"
                r"code availability|appendix|star", re.I), 0.45),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return re.sub(r"\s+([,.;:)\]])", r"\1", text)


def _local(tag: Any) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


# ---------------------------------------------------------------------------
# Europe PMC (JATS XML)
# ---------------------------------------------------------------------------

def _jats_text(el: ET.Element) -> str:
    parts: list[str] = [el.text or ""]
    for child in el:
        tag = _local(child.tag)
        if tag in ("disp-formula", "inline-formula", "math"):
            tex = child.find(".//{*}tex-math")
            parts.append(f" ${_clean(tex.text or '')}$ " if tex is not None and tex.text else " [公式] ")
        elif tag in ("fig", "table-wrap", "supplementary-material"):
            pass
        else:
            parts.append(_jats_text(child))
            if tag in ("p", "title", "label", "list-item"):
                parts.append(" ")
        parts.append(child.tail or "")
    return "".join(parts)


def _title_of(sec: ET.Element) -> str:
    title = sec.find("{*}title")
    return _clean(_jats_text(title)) if title is not None else ""


def _jats_table(tw: ET.Element) -> str:
    label = _clean(tw.findtext("{*}label") or "")
    caption_el = tw.find("{*}caption")
    caption = _clean(_jats_text(caption_el)) if caption_el is not None else ""
    rows = []
    for tr in tw.iter():
        if _local(tr.tag) != "tr":
            continue
        cells = [_clean(_jats_text(c)) for c in tr if _local(c.tag) in ("td", "th")]
        if any(cells):
            rows.append(" | ".join(cells))
    body = "\n".join(rows)
    if len(body) > 2500:
        body = body[:2500] + " …"
    return "\n".join(x for x in (f"{label} {caption}".strip(), body) if x)


def parse_jats(xml_text: str) -> list[dict[str, str]]:
    """Top-level body sections as ``[{title, text}]`` plus figure legends and tables."""
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    body = next((el for el in root.iter() if _local(el.tag) == "body"), None)
    if body is None:
        return []
    sections: list[dict[str, str]] = []
    figures: list[str] = []
    tables: list[str] = []
    loose: list[str] = []

    def collect(sec: ET.Element, depth: int, out: list[str]) -> None:
        for child in sec:
            tag = _local(child.tag)
            if tag == "title":
                continue
            if tag in ("p", "list", "disp-quote", "statement"):
                text = _clean(_jats_text(child))
                if text:
                    out.append(text)
            elif tag == "sec":
                title = _title_of(child)
                if title and _SKIP_TITLES.search(title):
                    continue
                if title:
                    out.append(f"【{title}】")
                collect(child, depth + 1, out)
            elif tag == "fig":
                label = _clean(child.findtext("{*}label") or "")
                cap = child.find("{*}caption")
                if cap is not None:
                    figures.append(_clean(f"{label} {_jats_text(cap)}"))
            elif tag == "table-wrap":
                table = _jats_table(child)
                if table:
                    tables.append(table)
            elif tag in ("fig-group", "table-wrap-group", "boxed-text"):
                collect(child, depth + 1, out)

    for child in body:
        tag = _local(child.tag)
        if tag == "sec":
            title = _title_of(child)
            if title and _SKIP_TITLES.search(title):
                continue
            out: list[str] = []
            collect(child, 1, out)
            if out:
                sections.append({"title": title or "Section", "text": "\n".join(out)})
        else:
            wrapper = ET.Element("sec")
            wrapper.append(child)
            collect(wrapper, 1, loose)
    if loose:
        sections.insert(0, {"title": "Main text", "text": "\n".join(loose)})
    if figures:
        sections.append({"title": "Figure legends", "text": "\n".join(figures)})
    if tables:
        sections.append({"title": "Tables", "text": "\n\n".join(tables)})
    return sections


# ---------------------------------------------------------------------------
# arXiv HTML (LaTeXML)
# ---------------------------------------------------------------------------

class _ArxivHTML(HTMLParser):
    _BLOCK = {"p", "figcaption", "li", "td", "th", "tr", "h2", "h3", "h4", "h5"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[dict[str, str]] = []
        self.figures: list[str] = []
        self._title: str | None = None
        self._buf: list[str] = []
        self._text: list[str] = []
        self._heading: str | None = None
        self._skip_depth = 0
        self._skip_tag: str | None = None
        self._stack: list[tuple[str, bool]] = []
        self._in_caption = False
        self._caption: list[str] = []
        self._started = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        cls = a.get("class") or ""
        if self._skip_depth:
            if tag == self._skip_tag:
                self._skip_depth += 1
            return
        if tag == "math":
            alt = a.get("alttext") or ""
            self._emit(f" ${alt}$ " if alt else " [公式] ")
            self._skip_tag, self._skip_depth = "math", 1
            return
        skip_classes = ("ltx_bibliography", "ltx_authors", "ltx_abstract", "ltx_page_footer", "ltx_role_footnote")
        if tag in ("script", "style", "nav", "header", "footer", "button") or any(c in cls for c in skip_classes):
            self._skip_tag, self._skip_depth = tag, 1
            return
        if tag == "article":
            self._started = True
        if tag in ("h2", "h3", "h4") and self._started:
            self._heading = tag
            self._buf = []
        if tag == "figcaption":
            self._in_caption, self._caption = True, []
        if tag in self._BLOCK and tag not in ("h2", "h3", "h4"):
            self._emit(" " if tag in ("td", "th") else "\n")

    def handle_endtag(self, tag: str) -> None:
        if self._skip_depth:
            if tag == self._skip_tag:
                self._skip_depth -= 1
                if not self._skip_depth:
                    self._skip_tag = None
            return
        if tag == self._heading:
            heading = _clean("".join(self._buf))
            heading = re.sub(r"^(\d+(\.\d+)*|[A-Z](\.\d+)*)\s+", "", heading)
            self._heading = None
            if tag == "h2":
                self._flush()
                self._title = heading
            elif heading:
                self._text.append(f"\n【{heading}】\n")
            return
        if tag == "figcaption":
            self._in_caption = False
            cap = _clean("".join(self._caption))
            if cap:
                self.figures.append(cap)
        if tag in ("td", "th"):
            self._emit(" |")

    def handle_data(self, data: str) -> None:
        if self._skip_depth or not self._started:
            return
        self._emit(data)

    def _emit(self, text: str) -> None:
        if self._heading:
            self._buf.append(text)
        elif self._in_caption:
            self._caption.append(text)
        else:
            self._text.append(text)

    def _flush(self) -> None:
        text = "\n".join(_clean(line) for line in "".join(self._text).split("\n"))
        text = re.sub(r"\n{2,}", "\n", text).strip()
        if text and not (self._title and _SKIP_TITLES.search(self._title)):
            self.sections.append({"title": self._title or "Main text", "text": text})
        self._text = []

    def result(self) -> list[dict[str, str]]:
        self._flush()
        sections = [s for s in self.sections if len(s["text"]) > 40]
        if self.figures:
            sections.append({"title": "Figure and table captions", "text": "\n".join(self.figures)})
        return sections


def parse_arxiv_html(html: str) -> list[dict[str, str]]:
    parser = _ArxivHTML()
    parser.feed(html)
    parser.close()
    return parser.result()


# ---------------------------------------------------------------------------
# Fetch + cache
# ---------------------------------------------------------------------------

def _cache_path(paper_id: str):
    digest = hashlib.sha1(paper_id.encode("utf-8")).hexdigest()[:20]
    return config.FULLTEXT_CACHE_DIR / f"{digest}.json"


def _read_cache(paper_id: str) -> dict[str, Any] | None:
    path = _cache_path(paper_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    if data.get("missing"):
        checked = datetime.fromisoformat(data.get("checked_at", "1970-01-01T00:00:00+00:00"))
        if datetime.now(timezone.utc) - checked > timedelta(days=config.FULLTEXT_CACHE_DAYS_MISSING):
            return None
    return data


def _write_cache(paper_id: str, data: dict[str, Any]) -> None:
    path = _cache_path(paper_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def candidates(paper: dict[str, Any]) -> list[tuple[str, str]]:
    out = []
    pmcid = (paper.get("pmcid") or "").strip().upper()
    if pmcid:
        if not pmcid.startswith("PMC"):
            pmcid = "PMC" + pmcid
        out.append(("Europe PMC", EUROPEPMC_FULLTEXT.format(pmcid=pmcid)))
    arxiv_id = re.sub(r"v\d+$", "", (paper.get("arxiv_id") or "").strip())
    if arxiv_id:
        out.append(("arXiv", ARXIV_HTML.format(arxiv_id=arxiv_id)))
    return out


def get_fulltext(paper: dict[str, Any], client: HttpClient | None = None, refresh: bool = False) -> dict[str, Any] | None:
    """Open-access full text as ``{source, url, sections}``, or ``None`` if unavailable."""
    pid = paper.get("id") or ""
    if not pid:
        return None
    if not refresh:
        cached = _read_cache(pid)
        if cached is not None:
            return None if cached.get("missing") else cached
    sources = candidates(paper)
    if not sources:
        return None
    client = client or get_client()
    tried = []
    for source, url in sources:
        try:
            resp = client.get(url, timeout=60)
            sections = parse_jats(resp.text) if source == "Europe PMC" else parse_arxiv_html(resp.text)
        except httpx.HTTPStatusError as exc:
            tried.append(f"{source}: HTTP {exc.response.status_code}")
            continue
        except (httpx.TransportError, ET.ParseError, ValueError) as exc:
            tried.append(f"{source}: {type(exc).__name__}")
            logger.info("Full text from %s failed for %s: %s", source, pid, exc)
            continue
        chars = sum(len(s["text"]) for s in sections)
        if chars < 1500:
            tried.append(f"{source}: too short")
            continue
        doc = {"id": pid, "source": source, "url": url, "sections": sections, "chars": chars, "fetched_at": _now()}
        _write_cache(pid, doc)
        return doc
    _write_cache(pid, {"id": pid, "missing": True, "checked_at": _now(), "tried": tried})
    return None


def _weight(title: str) -> float:
    for pattern, weight in _PRIORITY:
        if pattern.search(title):
            return weight
    return 0.7


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    stop = max(cut.rfind("。"), cut.rfind(". "), cut.rfind("\n"))
    if stop > limit * 0.6:
        cut = cut[: stop + 1]
    return cut.rstrip() + " …（此节已截断）"


def budget_sections(sections: list[dict[str, str]], budget: int) -> list[dict[str, str]]:
    """Fit sections into ``budget`` characters, trimming methods before results/discussion."""
    total = sum(len(s["text"]) for s in sections)
    if total <= budget:
        return sections
    weights = [_weight(s["title"]) for s in sections]
    lo, hi = 0.0, float(max(len(s["text"]) for s in sections))
    for _ in range(40):
        mid = (lo + hi) / 2
        used = sum(min(len(s["text"]), mid * w) for s, w in zip(sections, weights))
        lo, hi = (mid, hi) if used <= budget else (lo, mid)
    return [{"title": s["title"], "text": _truncate(s["text"], int(lo * w))}
            for s, w in zip(sections, weights) if int(lo * w) >= 200]


def as_prompt_text(doc: dict[str, Any], budget: int) -> str:
    return "\n\n".join(f"## {s['title']}\n{s['text']}" for s in budget_sections(doc["sections"], budget))
