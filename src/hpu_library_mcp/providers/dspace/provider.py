"""DSpaceProvider — hiện thực ResourceProvider cho nguồn 'dspace'.

Chỉ còn BUSINESS LOGIC dùng chung mọi phiên bản DSpace (enforce quyền, audit, orchestrate
tìm kiếm/semantic/bóc text) — mọi chi tiết REST/Solr cụ thể theo phiên bản nằm ở
`DSpaceAdapter` (`adapter_base.py` + `adapter_v6.py`), chọn theo `Settings.dspace_version`
— xem 02-architecture.md §4.2 và docs/DECISIONS.md (mục tách Adapter). Đổi 6.3 → v10
(NFR-4) = viết `DSpace10Adapter` mới, KHÔNG sửa file này.

get_text() (Sprint 4) luôn gọi self.get() trước để enforce quyền + ghi audit trước khi
bóc/trả bất kỳ nội dung nào.
"""

from __future__ import annotations

import asyncio
from typing import Any

from hpu_library_mcp.config import Settings
from hpu_library_mcp.errors import ForbiddenError, NotFoundError, NotImplementedYetError, UpstreamError
from hpu_library_mcp.logging_setup import get_logger
from hpu_library_mcp.models import (
    ALL_ACCESS_LEVELS,
    AccessLevel,
    BitstreamLink,
    Chunk,
    Citation,
    DocumentText,
    DocumentTextPage,
    Health,
    Node,
    Resource,
    SearchResult,
    SearchResultItem,
    Stats,
)
from hpu_library_mcp.providers.base import ResourceProvider
from hpu_library_mcp.providers.dspace.adapter_base import DSpaceAdapter
from hpu_library_mcp.providers.dspace.adapter_v6 import DSpace6Adapter
from hpu_library_mcp.providers.dspace.client import DSpaceRestClient
from hpu_library_mcp.providers.dspace.solr_client import SolrClient
from hpu_library_mcp.security.audit import audit_access
from hpu_library_mcp.text.extraction import extract_pages, find_matches
from hpu_library_mcp.vector.embedding import EmbeddingProvider
from hpu_library_mcp.vector.store import VectorStore

logger = get_logger(__name__)


def _build_default_adapter(
    settings: Settings, client: DSpaceRestClient | None, solr_client: SolrClient | None
) -> DSpaceAdapter:
    resolved_client = client or DSpaceRestClient(
        base_url=settings.dspace_rest_base_url,
        timeout=settings.dspace_http_timeout_seconds,
        service_email=settings.dspace_service_email,
        service_password=settings.dspace_service_password.get_secret_value(),
    )
    resolved_solr = solr_client or SolrClient(
        base_url=settings.dspace_solr_base_url,
        core=settings.dspace_solr_search_core,
        timeout=settings.dspace_http_timeout_seconds,
    )
    if settings.dspace_version == "6.3":
        return DSpace6Adapter(client=resolved_client, solr_client=resolved_solr, settings=settings)
    # v10: "Sau GĐ1" theo 07-sprints.md — báo lỗi rõ ràng thay vì âm thầm chạy sai adapter.
    raise NotImplementedYetError("DSpace10Adapter", "Sau GĐ1 (khi lên DSpace v10) — xem 07-sprints.md")


class DSpaceProvider(ResourceProvider):
    source = "dspace"

    def __init__(
        self,
        *,
        settings: Settings,
        client: DSpaceRestClient | None = None,
        solr_client: SolrClient | None = None,
        adapter: DSpaceAdapter | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        vector_store: VectorStore | None = None,
    ) -> None:
        self._settings = settings
        self._adapter = adapter or _build_default_adapter(settings, client, solr_client)
        # Không tự dựng mặc định (cần GEMINI_API_KEY/DATABASE_URL thật) — server.py tự
        # quyết định có cắm hay không; thiếu thì semantic_search báo lỗi rõ ràng khi gọi.
        self._embedding_provider = embedding_provider
        self._vector_store = vector_store

    async def aclose(self) -> None:
        await self._adapter.aclose()

    @staticmethod
    def _enforce_access(
        access_level: AccessLevel, allowed_levels: tuple[AccessLevel, ...] | None, *, item_id: str
    ) -> None:
        # allowed_levels=None: chưa nối tầng auth/API key (vd gọi trực tiếp không qua
        # server.py) -> không lọc, xem base.py.
        granted = allowed_levels is None or access_level in allowed_levels
        audit_access(item_id=item_id, access_level=access_level, granted=granted)
        if not granted:
            logger.warning("access_denied item_id=%s access_level=%s", item_id, access_level)
            raise ForbiddenError()

    # --- Sprint 1 ---

    async def get(self, id: str, *, allowed_levels: tuple[AccessLevel, ...] | None = None) -> Resource:
        resource = await self._adapter.resolve_item(id)
        self._enforce_access(resource.access_level, allowed_levels, item_id=resource.id)
        return resource

    async def list_communities(
        self, *, parent: str | None = None, allowed_levels: tuple[AccessLevel, ...] | None = None
    ) -> list[Node]:
        return await self._adapter.list_communities(parent=parent)

    async def list_collections(
        self, *, parent: str | None = None, allowed_levels: tuple[AccessLevel, ...] | None = None
    ) -> list[Node]:
        return await self._adapter.list_collections(parent=parent)

    async def get_recent_items(
        self,
        *,
        collection: str | None = None,
        limit: int = 10,
        allowed_levels: tuple[AccessLevel, ...] | None = None,
    ) -> list[Resource]:
        limit = max(1, min(limit, 100))
        candidates = await self._adapter.list_recent_candidates(collection=collection, limit=limit)

        resources: list[Resource] = []
        for resource in candidates:
            try:
                self._enforce_access(resource.access_level, allowed_levels, item_id=resource.id)
            except ForbiddenError:
                continue  # ẩn khỏi danh sách thay vì lỗi cả trang (06-test-plan §2.4)
            resources.append(resource)
        return resources

    async def get_bitstream_link(
        self,
        item_id: str,
        bitstream_id: str,
        *,
        allowed_levels: tuple[AccessLevel, ...] | None = None,
    ) -> BitstreamLink:
        file = await self._adapter.get_bitstream(item_id, bitstream_id)
        self._enforce_access(file.access_level, allowed_levels, item_id=item_id)
        return BitstreamLink(
            url=file.bitstream_link, requires_auth=file.access_level != "public", access_level=file.access_level
        )

    async def health(self) -> Health:
        return await self._adapter.health()

    # --- Sprint 2 ---

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
        page = max(1, page)
        page_size = max(1, min(page_size, 100))

        total, hits, facets_out = await self._adapter.search_candidates(
            query=query, scope=scope, filters=filters, facets=facets, page=page, page_size=page_size
        )

        async def _fetch_result_item(handle: str, highlights: list[str]) -> SearchResultItem | None:
            try:
                resource = await self.get(handle, allowed_levels=allowed_levels)
            except (ForbiddenError, NotFoundError):
                return None  # ẩn khỏi kết quả thay vì lỗi cả trang (06-test-plan §2.4)
            except UpstreamError:
                logger.warning("search_item_lookup_failed handle=%s", handle)
                return None
            return SearchResultItem(**resource.model_dump(), highlights=highlights)

        fetched = await asyncio.gather(*(_fetch_result_item(handle, hl) for handle, hl in hits))
        results = [item for item in fetched if item is not None]
        citations = [Citation(id=item.id, url=item.url) for item in results]

        return SearchResult(
            total=total, page=page, page_size=page_size, results=results, facets=facets_out, citations=citations
        )

    # --- Sprint 3 ---

    async def semantic_search(
        self,
        query: str,
        *,
        k: int = 8,
        filters: dict[str, Any] | None = None,
        allowed_levels: tuple[AccessLevel, ...] | None = None,
    ) -> list[Chunk]:
        # `filters` (collection/year_from/type) CHƯA được áp dụng — SQL semantic hiện bám
        # đúng nguyên văn 04-data-model.md §2 (chỉ lọc access_level). Xem docs/DECISIONS.md
        # Sprint 3 lý do chưa mở rộng lọc theo meta JSONB.
        if self._embedding_provider is None or self._vector_store is None:
            raise UpstreamError(
                "Tìm kiếm ngữ nghĩa chưa được cấu hình (thiếu GEMINI_API_KEY hoặc DATABASE_URL)."
            )
        levels = allowed_levels if allowed_levels else ALL_ACCESS_LEVELS
        [query_embedding] = await self._embedding_provider.embed([query], task_type="query")
        chunks = await self._vector_store.semantic_search(
            embedding=query_embedding, source=self.source, allowed_levels=levels, k=k
        )
        # Audit truy cập internal/restricted qua semantic search — trước đây chỉ lọc bằng
        # SQL WHERE access_level = ANY(...), không đi qua audit_access như get()/search()
        # (05-security.md §6 yêu cầu audit mọi lần chạm tài liệu internal/restricted, không
        # chỉ riêng Tầng 2). granted luôn True ở đây vì VectorStore đã lọc SQL trước khi trả
        # — chunk không được phép sẽ không bao giờ xuất hiện trong danh sách này.
        for chunk in chunks:
            audit_access(item_id=chunk.item_id, access_level=chunk.access_level, granted=True)
        return chunks

    # --- Sprint 4 ---

    async def get_text(
        self,
        id: str,
        *,
        query: str | None = None,
        page: int | None = None,
        allowed_levels: tuple[AccessLevel, ...] | None = None,
    ) -> DocumentText:
        # self.get() enforce quyền + ghi audit trước (05-security.md §6) — KHÔNG bóc/trả
        # nội dung nếu không đủ quyền, dù có bóc được hay không.
        resource = await self.get(id, allowed_levels=allowed_levels)

        pdf_files = [f for f in resource.files if f.mime == "application/pdf"]
        if not pdf_files:
            raise NotFoundError("Tài liệu này không có tệp PDF để bóc nội dung.")
        target = pdf_files[0]

        content = await self._adapter.download_bitstream_bytes(target)
        max_pages = self._settings.text_extract_max_pages
        pages_text, truncated = await asyncio.to_thread(
            extract_pages, content, mime=target.mime, max_pages=max_pages
        )

        result_pages: list[DocumentTextPage] = []
        if page is not None:
            index = page - 1
            if 0 <= index < len(pages_text):
                text = pages_text[index]
                matches = find_matches(text, query) if query else []
                result_pages.append(DocumentTextPage(page=page, text=text, matches=matches))
        else:
            for idx, text in enumerate(pages_text, start=1):
                matches = find_matches(text, query) if query else []
                if query and not matches:
                    continue  # find_in_document: chỉ trả trang có khớp
                result_pages.append(DocumentTextPage(page=idx, text=text, matches=matches))

        return DocumentText(
            id=resource.id, pages=result_pages, truncated=truncated, access_level=resource.access_level
        )

    async def stats(
        self, *, group_by: list[str] | None = None, allowed_levels: tuple[AccessLevel, ...] | None = None
    ) -> Stats:
        group_by = group_by or ["type", "year"]
        total, by = await self._adapter.stats_facets(group_by=group_by, allowed_levels=allowed_levels)
        return Stats(total_items=total, by=by)
