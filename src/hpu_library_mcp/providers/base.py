"""Interface ResourceProvider — xem 02-architecture.md §4.1.

Mọi tool gọi qua interface này, không gọi thẳng DSpace (nguyên tắc #2).
Tham số `allowed_levels` mang theo mức truy cập mà caller (API key) được phép thấy;
Sprint 1 CHƯA có tầng auth/API key (xem 05-security.md, Sprint 4) nên mặc định None
= chưa lọc. Ký hiệu tham số có sẵn ngay từ đầu để Sprint 4 cắm phân quyền vào mà
không phải đổi interface (nguyên tắc #5: phân quyền là bất biến ở mọi đường ra dữ liệu).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from hpu_library_mcp.models import (
    AccessLevel,
    BitstreamLink,
    Chunk,
    DocumentText,
    Health,
    Node,
    Resource,
    SearchResult,
    Stats,
)


class ResourceProvider(ABC):
    """1 nguồn dữ liệu (vd DSpace). Thêm nguồn mới = 1 class implement interface này."""

    source: str

    @abstractmethod
    async def search(
        self,
        query: str,
        *,
        filters: dict[str, Any] | None = None,
        scope: str = "metadata",
        facets: list[str] | None = None,
        page: int = 1,
        page_size: int = 10,
        allowed_levels: tuple[AccessLevel, ...] | None = None,
    ) -> SearchResult:
        """FR-1/FR-2 — search_library. Hiện thực ở Sprint 2."""

    @abstractmethod
    async def semantic_search(
        self,
        query: str,
        *,
        k: int = 8,
        filters: dict[str, Any] | None = None,
        allowed_levels: tuple[AccessLevel, ...] | None = None,
    ) -> list[Chunk]:
        """FR-3 — semantic_search_documents (Tầng 3). Hiện thực ở Sprint 3."""

    @abstractmethod
    async def get(self, id: str, *, allowed_levels: tuple[AccessLevel, ...] | None = None) -> Resource:
        """FR-4 — get_item. Sprint 1."""

    @abstractmethod
    async def get_text(
        self,
        id: str,
        *,
        query: str | None = None,
        page: int | None = None,
        allowed_levels: tuple[AccessLevel, ...] | None = None,
    ) -> DocumentText:
        """FR-5 — get_document_text/find_in_document (Tầng 2). Hiện thực ở Sprint 4."""

    @abstractmethod
    async def list_communities(
        self, *, parent: str | None = None, allowed_levels: tuple[AccessLevel, ...] | None = None
    ) -> list[Node]:
        """FR-6. Sprint 1."""

    @abstractmethod
    async def list_collections(
        self, *, parent: str | None = None, allowed_levels: tuple[AccessLevel, ...] | None = None
    ) -> list[Node]:
        """FR-6. Sprint 1."""

    @abstractmethod
    async def get_recent_items(
        self,
        *,
        collection: str | None = None,
        limit: int = 10,
        allowed_levels: tuple[AccessLevel, ...] | None = None,
    ) -> list[Resource]:
        """FR-6. Sprint 1."""

    @abstractmethod
    async def get_bitstream_link(
        self,
        item_id: str,
        bitstream_id: str,
        *,
        allowed_levels: tuple[AccessLevel, ...] | None = None,
    ) -> BitstreamLink:
        """Sprint 1."""

    @abstractmethod
    async def stats(
        self, *, group_by: list[str] | None = None, allowed_levels: tuple[AccessLevel, ...] | None = None
    ) -> Stats:
        """Sprint 2 (dựa trên facet Solr)."""

    @abstractmethod
    async def health(self) -> Health:
        """Sprint 1."""
