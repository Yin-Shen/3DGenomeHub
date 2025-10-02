"""High-level interface for the 3D genome knowledge base."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

from .config import DEFAULT_DATA_FILE, DEFAULT_DB_PATH, DEFAULT_INDEX_PATH
from .ingestion.loader import KnowledgeBaseRepository, ingest_bundle
from .ingestion.schema import KnowledgeBaseBundle, load_bundle
from .models import Resource
from .pipelines.update import refresh_knowledge_base
from .utils.embeddings import TfidfEmbeddingStore
from .utils.logging import configure_logging

LOGGER = configure_logging(name="three_d_genome_hub.core")


@dataclass
class SearchResult:
    resource: Resource
    score: float


class KnowledgeBase:
    """Wrapper combining storage and retrieval."""

    def __init__(
        self,
        repository: KnowledgeBaseRepository,
        index_path: Path = DEFAULT_INDEX_PATH,
    ) -> None:
        self.repository = repository
        self.index_path = index_path
        self._embedding_store: Optional[TfidfEmbeddingStore] = None

    # ------------------------------------------------------------------
    # Data ingestion helpers
    # ------------------------------------------------------------------
    def ingest_files(self, paths: Iterable[Path]) -> int:
        path_list = [Path(p) for p in paths]
        if not path_list:
            raise ValueError("No data files provided for ingestion")
        first_bundle = load_bundle(path_list[0])
        bundle = KnowledgeBaseBundle(metadata=first_bundle.metadata, resources=[])
        resources = []
        for path in path_list:
            LOGGER.info("Loading resource file: %s", path)
            loaded = load_bundle(path)
            resources.extend(loaded.resources)
        bundle.resources = resources
        count = ingest_bundle(bundle, self.repository)
        LOGGER.info("Ingested %s resources", count)
        return count

    def ingest_default_sample(self) -> int:
        return self.ingest_files([DEFAULT_DATA_FILE])

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------
    def build_index(self, output_path: Optional[Path] = None) -> Path:
        df = self.repository.fetch_all()
        if df.empty:
            raise RuntimeError("No resources available to build an index.")
        vectorizer = TfidfVectorizer(stop_words="english", max_features=5000)
        matrix = vectorizer.fit_transform(_compose_corpus(df))
        store = TfidfEmbeddingStore(vectorizer, matrix)
        output_path = output_path or self.index_path
        store.save(output_path)
        self._embedding_store = store
        LOGGER.info("Stored TF-IDF index at %s", output_path)
        return output_path

    def load_index(self, path: Optional[Path] = None) -> None:
        target = path or self.index_path
        if not target.exists():
            raise FileNotFoundError(f"Index file not found at {target}")
        self._embedding_store = TfidfEmbeddingStore.load(target)
        LOGGER.info("Loaded TF-IDF index from %s", target)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def search(self, query: str, top_k: int = 5) -> List[SearchResult]:
        if self._embedding_store is None:
            self.load_index()
        assert self._embedding_store is not None
        df = self.repository.fetch_all()
        matches = self._embedding_store.query([query], top_k=top_k)[0]
        resources = []
        for idx, score in matches:
            row = df.iloc[idx]
            resource = row_to_resource(row)
            resources.append(SearchResult(resource=resource, score=score))
        return resources

    def keyword_search(self, keyword: str) -> List[Resource]:
        df = self.repository.search_by_keyword(keyword)
        return [row_to_resource(row) for _, row in df.iterrows()]

    # ------------------------------------------------------------------
    # Refresh workflows
    # ------------------------------------------------------------------
    def refresh(self, search_terms: Optional[Iterable[str]] = None) -> int:
        """Update the repository by combining curated data with live sources."""

        terms: Iterable[str] = search_terms or ("3D genome", "chromatin architecture")
        count = refresh_knowledge_base(self.repository, search_terms=tuple(terms))
        self.build_index(self.index_path)
        return count


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _compose_corpus(df: pd.DataFrame) -> List[str]:
    corpus = []
    for _, row in df.iterrows():
        bits = [row.get("title", ""), row.get("summary", ""), row.get("tags", "")]
        corpus.append(" ".join(filter(None, bits)))
    return corpus


def row_to_resource(row: pd.Series) -> Resource:
    assets = _load_optional_json_list(row.get("assets"))
    datasets = _load_optional_json_list(row.get("datasets"))
    modules = _load_optional_json_list(row.get("modules"))
    tags = _split_field(row.get("tags"), separator=",")
    prerequisites = _split_field(row.get("prerequisites"), separator=";")
    learning_objectives = _split_field(row.get("learning_objectives"), separator=";")
    duration_value = row.get("duration_minutes")
    year_value = row.get("year")
    return Resource(
        id=row["id"],
        title=row["title"],
        type=row["type"],
        level=row["level"],
        category=row["category"],
        summary=row["summary"],
        tags=tags,
        author=row.get("author"),
        source=row.get("source"),
        url=row.get("url"),
        language=row.get("language"),
        doi=row.get("doi"),
        year=int(year_value) if pd.notna(year_value) else None,
        code=row.get("code"),
        slides=row.get("slides"),
        recommended_age=row.get("recommended_age"),
        duration_minutes=int(duration_value) if pd.notna(duration_value) else None,
        prerequisites=prerequisites,
        learning_objectives=learning_objectives,
        assets=assets or [],
        datasets=datasets or [],
        modules=modules or [],
    )


def bootstrap_sample_database() -> KnowledgeBase:
    repo = KnowledgeBaseRepository(DEFAULT_DB_PATH)
    kb = KnowledgeBase(repo, index_path=DEFAULT_INDEX_PATH)
    if not DEFAULT_DB_PATH.exists():
        kb.ingest_default_sample()
    if DEFAULT_INDEX_PATH.exists():
        kb.load_index(DEFAULT_INDEX_PATH)
    else:
        kb.build_index(DEFAULT_INDEX_PATH)
    return kb


def _load_optional_json_list(value):
    if not value:
        return None
    if isinstance(value, str):
        try:
            data = json.loads(value)
            if isinstance(data, dict):
                # handle legacy format {"assets": [...]}
                data = next(iter(data.values()))
            return data
        except json.JSONDecodeError:
            return None
    return value


def _split_field(value, separator: str) -> List[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    text = str(value).strip()
    if not text:
        return []
    return [item.strip() for item in text.split(separator) if item.strip()]


__all__ = ["KnowledgeBase", "SearchResult", "bootstrap_sample_database", "row_to_resource"]
