"""Pydantic models describing knowledge base entities."""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field, HttpUrl, validator


class Asset(BaseModel):
    """Additional downloadable material."""

    type: str = Field(..., description="Type of asset such as worksheet, slide, video")
    title: str
    url: HttpUrl


class DatasetRef(BaseModel):
    """Reference to an external dataset."""

    name: str
    url: HttpUrl


class Module(BaseModel):
    """Curriculum module description."""

    name: str
    duration_hours: Optional[float] = None


class Resource(BaseModel):
    """Generic knowledge base entry."""

    id: str
    title: str
    type: str
    level: str
    category: str
    summary: str
    tags: List[str] = Field(default_factory=list)
    author: Optional[str]
    source: Optional[str]
    url: Optional[HttpUrl]
    language: Optional[str]
    doi: Optional[str]
    year: Optional[int]
    code: Optional[HttpUrl]
    slides: Optional[HttpUrl]
    recommended_age: Optional[str]
    duration_minutes: Optional[int]
    prerequisites: List[str] = Field(default_factory=list)
    learning_objectives: List[str] = Field(default_factory=list)
    assets: List[Asset] = Field(default_factory=list)
    datasets: List[DatasetRef] = Field(default_factory=list)
    modules: List[Module] = Field(default_factory=list)

    @validator("year")
    def validate_year(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return value
        current_year = date.today().year
        if value < 1950 or value > current_year + 1:
            raise ValueError("Year is out of expected range")
        return value


class KnowledgeBaseMetadata(BaseModel):
    """Metadata about the knowledge base dataset."""

    version: str
    generated_at: str
    curated_by: Optional[str]


class KnowledgeBaseBundle(BaseModel):
    """Top-level structure for YAML import/export."""

    metadata: KnowledgeBaseMetadata
    resources: List[Resource]


__all__ = [
    "Asset",
    "DatasetRef",
    "Module",
    "Resource",
    "KnowledgeBaseMetadata",
    "KnowledgeBaseBundle",
]
