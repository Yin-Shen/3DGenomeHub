"""Pipeline script to build TF-IDF index for the knowledge base."""

from __future__ import annotations

from pathlib import Path

from ..config import DEFAULT_DB_PATH, DEFAULT_INDEX_PATH
from ..ingestion.loader import KnowledgeBaseRepository
from ..knowledge_base import KnowledgeBase
from ..utils.logging import configure_logging

LOGGER = configure_logging(name="three_d_genome_hub.pipeline")


def run(database: Path = DEFAULT_DB_PATH, output: Path = DEFAULT_INDEX_PATH) -> Path:
    """Create a TF-IDF index for resources."""

    LOGGER.info("Building index from %s", database)
    repo = KnowledgeBaseRepository(database)
    kb = KnowledgeBase(repo, index_path=output)
    path = kb.build_index(output)
    LOGGER.info("Index stored at %s", path)
    return path


if __name__ == "__main__":
    run()
