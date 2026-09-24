"""Saved AI outputs (interpretations, summaries, reviews, conversations) as Markdown files."""

from __future__ import annotations

import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from . import config
from .storage import load_json, save_json

KIND_LABELS = {
    "interpret": "AI 解读",
    "summary": "多篇总结",
    "compare": "对比分析",
    "review": "综述",
    "gaps": "研究空白与选题",
    "ask": "文献问答",
    "chat": "AI 讨论",
}

_lock = threading.Lock()


def _index_path() -> Path:
    return config.AI_NOTES_DIR / "index.json"


def list_notes() -> list[dict[str, Any]]:
    data = load_json(_index_path(), [])
    return data if isinstance(data, list) else []


def _slug(text: str) -> str:
    text = re.sub(r"[^\w一-鿿-]+", "-", text).strip("-")
    return text[:40] or "note"


def format_reference(ref: dict[str, Any]) -> str:
    authors = ref.get("authors") or []
    who = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "") if authors else "Unknown authors"
    link = f"https://doi.org/{ref['doi']}" if ref.get("doi") else (ref.get("url") or "")
    parts = [f"[{ref['n']}] {who} ({ref.get('year') or 'n.d.'}). {ref.get('title', '').rstrip('.')}."]
    if ref.get("journal"):
        parts.append(f"*{ref['journal']}*.")
    if link:
        parts.append(link)
    return " ".join(parts)


def render_markdown(note: dict[str, Any], content: str, references: list[dict[str, Any]]) -> str:
    meta = [KIND_LABELS.get(note["kind"], note["kind"]), f"模型：{note.get('model') or '-'}",
            f"生成时间：{note['created'][:16].replace('T', ' ')}"]
    if note.get("paper_ids"):
        meta.append(f"文献数：{len(note['paper_ids'])}")
    if note.get("basis"):
        meta.append(f"依据：{note['basis']}")
    lines = [f"# {note['title']}", "", "> " + " · ".join(meta), "", content.strip(), ""]
    if references:
        lines += ["## 参考文献", ""] + [format_reference(r) + "  " for r in references]
    return "\n".join(lines).rstrip() + "\n"


def save_note(kind: str, title: str, content: str, *, paper_ids: list[str] | None = None,
              references: list[dict[str, Any]] | None = None, model: str = "", basis: str = "",
              extra: dict[str, Any] | None = None) -> dict[str, Any]:
    created = datetime.now().isoformat(timespec="seconds")
    note = {
        "id": uuid.uuid4().hex[:12],
        "kind": kind,
        "title": title.strip()[:200] or KIND_LABELS.get(kind, kind),
        "created": created,
        "model": model,
        "basis": basis,
        "paper_ids": paper_ids or [],
    }
    if extra:
        note.update(extra)
    note["references"] = [{k: r.get(k) for k in ("n", "id", "title", "year", "journal", "doi", "url", "authors")}
                          for r in references or []]
    note["file"] = f"{created[:10]}-{note['id']}-{_slug(note['title'])}.md"
    config.AI_NOTES_DIR.mkdir(parents=True, exist_ok=True)
    (config.AI_NOTES_DIR / note["file"]).write_text(render_markdown(note, content, note["references"]), encoding="utf-8")
    with _lock:
        index = list_notes()
        index.insert(0, note)
        save_json(_index_path(), index)
    return note


def get_note(note_id: str) -> tuple[dict[str, Any], str] | None:
    for note in list_notes():
        if note["id"] == note_id:
            path = config.AI_NOTES_DIR / note["file"]
            if path.exists():
                return note, path.read_text(encoding="utf-8")
    return None


def delete_note(note_id: str) -> bool:
    with _lock:
        index = list_notes()
        keep = [n for n in index if n["id"] != note_id]
        if len(keep) == len(index):
            return False
        for note in index:
            if note["id"] == note_id:
                path = config.AI_NOTES_DIR / note["file"]
                if path.exists():
                    path.unlink()
        save_json(_index_path(), keep)
    return True


def latest_interpretation(paper_id: str) -> dict[str, Any] | None:
    for note in list_notes():
        if note["kind"] == "interpret" and note.get("paper_ids") == [paper_id]:
            return note
    return None


def note_body(markdown: str) -> str:
    """Strip the title/meta header and the generated reference list from a saved note."""
    body = re.sub(r"\A# .*\n\n> .*\n\n", "", markdown)
    return re.split(r"\n## 参考文献\n", body)[0].strip()
