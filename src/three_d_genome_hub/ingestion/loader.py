"""Data ingestion utilities."""

from __future__ import annotations

import sqlite3
import json
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

from ..models import KnowledgeBaseBundle, Resource
from ..utils.logging import configure_logging

LOGGER = configure_logging(name="three_d_genome_hub.ingestion")

RESOURCE_COLUMNS = [
    "id",
    "title",
    "type",
    "level",
    "category",
    "summary",
    "tags",
    "author",
    "source",
    "url",
    "language",
    "doi",
    "year",
    "code",
    "slides",
    "recommended_age",
    "duration_minutes",
    "prerequisites",
    "learning_objectives",
    "assets",
    "datasets",
    "modules",
]


def _resource_to_row(resource: Resource) -> dict:
    return {
        "id": resource.id,
        "title": resource.title,
        "type": resource.type,
        "level": resource.level,
        "category": resource.category,
        "summary": resource.summary,
        "tags": ",".join(resource.tags),
        "author": resource.author,
        "source": resource.source,
        "url": resource.url,
        "language": resource.language,
        "doi": resource.doi,
        "year": resource.year,
        "code": resource.code,
        "slides": resource.slides,
        "recommended_age": resource.recommended_age,
        "duration_minutes": resource.duration_minutes,
        "prerequisites": ";".join(resource.prerequisites),
        "learning_objectives": ";".join(resource.learning_objectives),
        "assets": json.dumps([asset.dict() for asset in resource.assets], ensure_ascii=False)
        if resource.assets
        else None,
        "datasets": json.dumps([dataset.dict() for dataset in resource.datasets], ensure_ascii=False)
        if resource.datasets
        else None,
        "modules": json.dumps([module.dict() for module in resource.modules], ensure_ascii=False)
        if resource.modules
        else None,
    }


class KnowledgeBaseRepository:
    """SQLite-backed storage for knowledge base resources."""

    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS resources (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    type TEXT NOT NULL,
                    level TEXT NOT NULL,
                    category TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    tags TEXT,
                    author TEXT,
                    source TEXT,
                    url TEXT,
                    language TEXT,
                    doi TEXT,
                    year INTEGER,
                    code TEXT,
                    slides TEXT,
                    recommended_age TEXT,
                    duration_minutes INTEGER,
                    prerequisites TEXT,
                    learning_objectives TEXT,
                    assets TEXT,
                    datasets TEXT,
                    modules TEXT
                )
                """
            )
            conn.commit()

    def upsert_resources(self, resources: Sequence[Resource]) -> int:
        rows = [_resource_to_row(resource) for resource in resources]
        df = pd.DataFrame(rows, columns=RESOURCE_COLUMNS)
        with self._connect() as conn:
            df.to_sql("resources", conn, if_exists="replace", index=False)
        LOGGER.info("Stored %s resources into %s", len(resources), self.database_path)
        return len(resources)

    def fetch_all(self) -> pd.DataFrame:
        with self._connect() as conn:
            return pd.read_sql_query("SELECT * FROM resources", conn)

    def fetch_by_ids(self, ids: Iterable[str]) -> pd.DataFrame:
        id_list = list(ids)
        if not id_list:
            return pd.DataFrame(columns=RESOURCE_COLUMNS)
        placeholders = ",".join("?" for _ in id_list)
        query = f"SELECT * FROM resources WHERE id IN ({placeholders})"
        with self._connect() as conn:
            return pd.read_sql_query(query, conn, params=id_list)

    def search_by_keyword(self, keyword: str) -> pd.DataFrame:
        like = f"%{keyword}%"
        with self._connect() as conn:
            return pd.read_sql_query(
                "SELECT * FROM resources WHERE title LIKE ? OR summary LIKE ? OR tags LIKE ?",
                conn,
                params=[like, like, like],
            )


def ingest_bundle(bundle: KnowledgeBaseBundle, repository: KnowledgeBaseRepository) -> int:
    return repository.upsert_resources(bundle.resources)


__all__ = ["KnowledgeBaseRepository", "ingest_bundle"]
