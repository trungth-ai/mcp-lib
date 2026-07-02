"""Schema tài nguyên chuẩn hóa dùng chung mọi nguồn — xem 04-data-model.md."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

AccessLevel = Literal["public", "internal", "restricted"]

ALL_ACCESS_LEVELS: tuple[AccessLevel, ...] = ("public", "internal", "restricted")


class ResourceFile(BaseModel):
    bitstream_id: str
    name: str
    mime: str | None = None
    size: int | None = None
    bitstream_link: str
    access_level: AccessLevel


class Resource(BaseModel):
    id: str
    source: str = "dspace"
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    type: str | None = None
    language: str | None = None
    abstract: str | None = None
    collection: str | None = None
    community: str | None = None
    url: str | None = None
    # Mặc định restricted (fail-safe) — xem 05-security.md §3 "nguyên tắc mặc định".
    access_level: AccessLevel = "restricted"
    files: list[ResourceFile] = Field(default_factory=list)
    raw_meta: dict[str, Any] = Field(default_factory=dict)


class Node(BaseModel):
    id: str
    name: str
    type: Literal["community", "collection"]
    count: int | None = None


class NodeList(BaseModel):
    nodes: list[Node] = Field(default_factory=list)


class Citation(BaseModel):
    id: str
    url: str | None = None
    page: int | None = None


class SearchResultItem(Resource):
    highlights: list[str] = Field(default_factory=list)


class SearchResult(BaseModel):
    """Kết quả search_library — Tầng 1/metadata (Sprint 2)."""

    total: int
    page: int
    page_size: int
    results: list[SearchResultItem] = Field(default_factory=list)
    facets: dict[str, dict[str, int]] = Field(default_factory=dict)
    citations: list[Citation] = Field(default_factory=list)


class Chunk(BaseModel):
    """Chunk ngữ nghĩa — Tầng 3 (Sprint 3)."""

    item_id: str
    chunk_index: int
    text: str
    score: float
    title: str | None = None
    url: str | None = None
    page: int | None = None
    access_level: AccessLevel = "restricted"


class DocumentTextPage(BaseModel):
    page: int | None = None
    text: str
    matches: list[str] = Field(default_factory=list)


class DocumentText(BaseModel):
    """Kết quả get_document_text/find_in_document — Tầng 2 (Sprint 4)."""

    id: str
    pages: list[DocumentTextPage] = Field(default_factory=list)
    truncated: bool = False
    access_level: AccessLevel = "restricted"


class BitstreamLink(BaseModel):
    url: str
    requires_auth: bool
    access_level: AccessLevel


class Stats(BaseModel):
    total_items: int
    by: dict[str, dict[str, int]] = Field(default_factory=dict)


class Health(BaseModel):
    status: Literal["ok", "degraded", "down"]
    detail: str | None = None
