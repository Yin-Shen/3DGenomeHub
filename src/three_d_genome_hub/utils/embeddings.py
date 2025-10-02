"""Utility helpers for building and using text embeddings."""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


class TfidfEmbeddingStore:
    """Wrapper for TF-IDF vectorizer and document matrix."""

    def __init__(self, vectorizer: TfidfVectorizer, matrix):
        self.vectorizer = vectorizer
        self.matrix = matrix

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"vectorizer": self.vectorizer, "matrix": self.matrix}, path)

    @classmethod
    def load(cls, path: Path) -> "TfidfEmbeddingStore":
        payload = joblib.load(path)
        return cls(payload["vectorizer"], payload["matrix"])

    def query(self, texts: List[str], top_k: int = 5) -> List[List[Tuple[int, float]]]:
        query_matrix = self.vectorizer.transform(texts)
        similarities = cosine_similarity(query_matrix, self.matrix)
        results: List[List[Tuple[int, float]]] = []
        for row in similarities:
            indices = row.argsort()[::-1][:top_k]
            results.append([(int(idx), float(row[idx])) for idx in indices])
        return results


__all__ = ["TfidfEmbeddingStore"]
