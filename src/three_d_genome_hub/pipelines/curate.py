"""Utilities for semi-automatic curation of literature metadata."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List

from ..models import Resource


@dataclass
class LiteratureRecord:
    """Normalized metadata for ML/DL literature."""

    id: str
    title: str
    authors: str
    venue: str
    year: int
    url: str
    tags: List[str]

    def to_resource(self) -> Resource:
        return Resource(
            id=self.id,
            title=self.title,
            type="paper",
            level="research",
            category="ML-DL-Research",
            summary="",
            tags=self.tags,
            author=self.authors,
            source=self.venue,
            year=self.year,
            url=self.url,
        )


def export_to_csv(records: Iterable[LiteratureRecord], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["id", "title", "authors", "venue", "year", "url", "tags"]
    with output.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            row = asdict(record)
            row["tags"] = ";".join(record.tags)
            writer.writerow(row)


__all__ = ["LiteratureRecord", "export_to_csv"]
