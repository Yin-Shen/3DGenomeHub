"""FastAPI application exposing knowledge base endpoints and a web workspace."""

from __future__ import annotations

from pathlib import Path
from typing import List

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config import DEFAULT_DB_PATH, DEFAULT_INDEX_PATH
from ..ingestion.loader import KnowledgeBaseRepository
from ..knowledge_base import KnowledgeBase, row_to_resource
from ..models import Resource

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app = FastAPI(title="3DGenomeHub API", version="0.2.0")


class AppState:
    def __init__(self) -> None:
        self.kb: KnowledgeBase | None = None


default_categories: list[str] | None = None

default_levels: list[str] | None = None


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


def _cached_facets(kb: KnowledgeBase) -> tuple[list[str], list[str]]:
    global default_categories, default_levels
    if default_categories is None or default_levels is None:
        all_resources = kb.repository.fetch_all()
        default_categories = sorted(all_resources["category"].dropna().unique().tolist())
        default_levels = sorted(all_resources["level"].dropna().unique().tolist())
    return default_categories or [], default_levels or []


@app.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    q: str | None = Query(None, description="Search query"),
    category: str | None = Query(None, description="Filter by category"),
    level: str | None = Query(None, description="Filter by learner level"),
    status: str | None = Query(None, description="Status message"),
    kb: KnowledgeBase = Depends(get_kb),
) -> HTMLResponse:
    resources: List[Resource]
    if q:
        resources = [result.resource for result in kb.search(q, top_k=12)]
    else:
        df = kb.repository.fetch_all()
        if category:
            df = df[df["category"] == category]
        if level:
            df = df[df["level"] == level]
        resources = [row_to_resource(row) for _, row in df.iterrows()]
    categories, levels = _cached_facets(kb)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "resources": resources,
            "query": q or "",
            "category": category or "",
            "level": level or "",
            "status": status,
            "result_count": len(resources),
            "categories": categories,
            "levels": levels,
        },
    )


@app.post("/update")
async def trigger_update(
    background_tasks: BackgroundTasks,
    kb: KnowledgeBase = Depends(get_kb),
) -> RedirectResponse:
    def refresh() -> None:
        global default_categories, default_levels
        kb.refresh()
        default_categories = None
        default_levels = None

    background_tasks.add_task(refresh)
    return RedirectResponse(url="/?status=update-started", status_code=303)


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
