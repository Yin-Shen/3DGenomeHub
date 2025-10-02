"""FastAPI application exposing knowledge base endpoints."""

from __future__ import annotations

from typing import List

from fastapi import Depends, FastAPI, HTTPException, Query

from ..config import DEFAULT_DB_PATH, DEFAULT_INDEX_PATH
from ..ingestion.loader import KnowledgeBaseRepository
from ..knowledge_base import KnowledgeBase, row_to_resource
from ..models import Resource

app = FastAPI(title="3DGenomeHub API", version="0.1.0")


class AppState:
    def __init__(self) -> None:
        self.kb: KnowledgeBase | None = None


state = AppState()


def get_kb() -> KnowledgeBase:
    if state.kb is None:
        repo = KnowledgeBaseRepository(DEFAULT_DB_PATH)
        kb = KnowledgeBase(repo, index_path=DEFAULT_INDEX_PATH)
        if not DEFAULT_DB_PATH.exists():
            kb.ingest_default_sample()
        if DEFAULT_INDEX_PATH.exists():
            kb.load_index(DEFAULT_INDEX_PATH)
        else:
            kb.build_index(DEFAULT_INDEX_PATH)
        state.kb = kb
    return state.kb


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/resources", response_model=List[Resource])
def list_resources(
    category: str | None = Query(None, description="Filter by category"),
    level: str | None = Query(None, description="Filter by level"),
    kb: KnowledgeBase = Depends(get_kb),
) -> List[Resource]:
    df = kb.repository.fetch_all()
    if category:
        df = df[df["category"] == category]
    if level:
        df = df[df["level"] == level]
    return [row_to_resource(row) for _, row in df.iterrows()]


@app.get("/search", response_model=List[Resource])
def search_resources(
    q: str = Query(..., description="Search query"),
    top_k: int = Query(5, ge=1, le=20),
    kb: KnowledgeBase = Depends(get_kb),
) -> List[Resource]:
    results = kb.search(q, top_k=top_k)
    return [result.resource for result in results]


@app.get("/resources/{resource_id}", response_model=Resource)
def get_resource(resource_id: str, kb: KnowledgeBase = Depends(get_kb)) -> Resource:
    df = kb.repository.fetch_by_ids([resource_id])
    if df.empty:
        raise HTTPException(status_code=404, detail="Resource not found")
    return row_to_resource(df.iloc[0])


@app.on_event("startup")
def startup_event() -> None:
    get_kb()
