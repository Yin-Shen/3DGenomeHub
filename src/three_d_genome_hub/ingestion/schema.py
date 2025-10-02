"""Schema helpers for ingestion."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import yaml

from ..models import KnowledgeBaseBundle


def load_bundle(path: Path) -> KnowledgeBaseBundle:
    """Load YAML/JSON file and validate with pydantic."""

    if path.suffix.lower() in {".yaml", ".yml"}:
        content = yaml.safe_load(path.read_text(encoding="utf-8"))
    elif path.suffix.lower() == ".json":
        content = json.loads(path.read_text(encoding="utf-8"))
    else:
        raise ValueError(f"Unsupported file extension: {path.suffix}")
    return KnowledgeBaseBundle.parse_obj(content)


def flatten_resources(paths: Iterable[Path]) -> KnowledgeBaseBundle:
    """Combine multiple bundles into a single bundle."""

    metadata = None
    resources = []
    for path in paths:
        bundle = load_bundle(path)
        metadata = bundle.metadata
        resources.extend(bundle.resources)
    if metadata is None:
        raise ValueError("No metadata found from provided paths")
    return KnowledgeBaseBundle(metadata=metadata, resources=resources)


__all__ = ["load_bundle", "flatten_resources"]
