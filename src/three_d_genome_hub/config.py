"""Project configuration utilities."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
ARTIFACTS_DIR = DATA_DIR / "artifacts"
DEFAULT_DB_PATH = DATA_DIR / "knowledge_base.db"
DEFAULT_DATA_FILE = DATA_DIR / "sample-data.yml"
DEFAULT_INDEX_PATH = ARTIFACTS_DIR / "vector_index.pkl"


def get_env_path(name: str, default: Optional[Path] = None) -> Path:
    """Return a path from environment variables with a fallback."""

    value = os.getenv(name)
    if value:
        return Path(value)
    if default is not None:
        return default
    raise RuntimeError(f"Environment variable {name} is not set and no default provided")


__all__ = [
    "BASE_DIR",
    "DATA_DIR",
    "ARTIFACTS_DIR",
    "DEFAULT_DB_PATH",
    "DEFAULT_DATA_FILE",
    "DEFAULT_INDEX_PATH",
    "get_env_path",
]
