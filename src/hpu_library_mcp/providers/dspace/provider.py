"""DSpaceProvider — hiện thực ResourceProvider cho nguồn 'dspace', GĐ 6.3.

Sprint 1 hiện thực: get, list_communities, list_collections, get_recent_items,
get_bitstream_link, health. Các method còn lại (search, semantic_search, get_text,
stats) thuộc Sprint 2-4, tạm raise NotImplementedYetError.
"""

from __future__ import annotations

from typing import Any

from hpu_library_mcp.config import Settings
from hpu_library_mcp.errors import ForbiddenError, NotFoundError, NotImplementedYetError, UpstreamError
from hpu_library_mcp.logging_setup import get_logger
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
from hpu_library_mcp.providers.base import ResourceProvider
from hpu_library_mcp.providers.dspace.client import DSpaceRestClient
from hpu_library_mcp.providers.dspace.mapping import (
    extract_sort_date,
    infer_access_level,
    map_bitstream,
    map_collection_to_node,
    map_community_to_node,
    map_item_to_resource,
)

logger = get_logger(__name__)

_ITEM_EXPAND = "metadata,bitstreams,parentCollection,parentCommunityList"
# Số item tối đa tải để sắp xếp lấy "mới nhất" khi REST 6.x không hỗ trợ sort theo ngày trực tiếp.
_RECENT_ITEMS_OVERFETCH_CAP = 200


class DSpaceProvider(ResourceProvider):
    source = "dspace"

    def __init__(self, *, settings: Settings, client: DSpaceRestClient | None = None) -> None:
        self._settings = settings
        self._client = client or DSpaceRestClient(
            base_url=settings.dspace_rest_base_url,
            timeout=settings.dspace_http_timeout_seconds,
            service_email=settings.dspace_service_email,
            service_password=settings.dspace_service_password.get_secret_value(),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # --- helpers ---

    async def _resolve_item_by_id(self, id: str) -> dict[str, Any]:
        path = f"/handle/{id}" if "/" in id else f"/items/{id}"
        item = await self._client.get_json(path, params={"expand": _ITEM_EXPAND})
        if not item:
            raise NotFoundError("Không tìm thấy tài liệu trong hệ thống thư viện.")
        return item

    async def _get_item_policies(self, item_uuid: str | None) -> list[dict[str, Any]] | None:
        if not item_uuid:
            return None
        try:
            return await self._client.get_json(f"/items/{item_uuid}/policy")
        except (NotFoundError, UpstreamError):
            return None  # thiếu policy -> infer_access_level trả về restricted (fail-safe)

    @staticmethod
    def _enforce_access(
        access_level: AccessLevel, allowed_levels: tuple[AccessLevel, ...] | None, *, item_id: str
    ) -> None:
        if allowed_levels is None:
            return  # Sprint 1: chưa có tầng auth/API key -> không lọc (xem base.py)
        if access_level not in allowed_levels:
            logger.warning("access_denied item_id=%s access_level=%s", item_id, access_level)
            raise ForbiddenError()

    def _map_item(self, item: dict[str, Any], policies: list[dict[str, Any]] | None) -> Resource:
        return map_item_to_resource(
            item,
            rest_base_url=self._settings.dspace_rest_base_url,
            public_base_url=self._settings.dspace_public_base_url,
            resource_policies=policies,
        )

    # --- Sprint 1 ---

    async def get(self, id: str, *, allowed_levels: tuple[AccessLevel, ...] | None = None) -> Resource:
        item = await self._resolve_item_by_id(id)
        policies = await self._get_item_policies(item.get("uuid"))
        resource = self._map_item(item, policies)
        self._enforce_access(resource.access_level, allowed_levels, item_id=resource.id)
        return resource

    async def list_communities(
        self, *, parent: str | None = None, allowed_levels: tuple[AccessLevel, ...] | None = None
    ) -> list[Node]:
        path = f"/communities/{parent}/communities" if parent else "/communities/top-communities"
        raw = await self._client.get_json(path) or []
        return [map_community_to_node(c) for c in raw]

    async def list_collections(
        self, *, parent: str | None = None, allowed_levels: tuple[AccessLevel, ...] | None = None
    ) -> list[Node]:
        path = f"/communities/{parent}/collections" if parent else "/collections"
        raw = await self._client.get_json(path) or []
        return [map_collection_to_node(c) for c in raw]

    async def get_recent_items(
        self,
        *,
        collection: str | None = None,
        limit: int = 10,
        allowed_levels: tuple[AccessLevel, ...] | None = None,
    ) -> list[Resource]:
        limit = max(1, min(limit, 100))
        # REST 6.x không đảm bảo thứ tự theo ngày -> tải dư rồi sort phía client.
        # Giới hạn Sprint 1, đáng cân nhắc chuyển sang Solr (Tầng 1, Sprint 2) khi có sort thật.
        fetch_n = min(max(limit * 5, 50), _RECENT_ITEMS_OVERFETCH_CAP)
        path = f"/collections/{collection}/items" if collection else "/items"
        raw_items = await self._client.get_json(path, params={"limit": fetch_n, "expand": "metadata"}) or []
        raw_items_sorted = sorted(raw_items, key=extract_sort_date, reverse=True)[:limit]

        resources: list[Resource] = []
        for raw_item in raw_items_sorted:
            policies = await self._get_item_policies(raw_item.get("uuid"))
            resource = self._map_item(raw_item, policies)
            if allowed_levels is None or resource.access_level in allowed_levels:
                resources.append(resource)
        return resources

    async def get_bitstream_link(
        self,
        item_id: str,
        bitstream_id: str,
        *,
        allowed_levels: tuple[AccessLevel, ...] | None = None,
    ) -> BitstreamLink:
        item = await self._resolve_item_by_id(item_id)
        item_policies = await self._get_item_policies(item.get("uuid"))
        item_access_level = infer_access_level(item_policies)

        bitstream = next(
            (
                b
                for b in item.get("bitstreams") or []
                if str(b.get("uuid") or b.get("id") or "") == bitstream_id
            ),
            None,
        )
        if bitstream is None:
            raise NotFoundError("Không tìm thấy tệp trong tài liệu này.")

        try:
            bitstream_policies = await self._client.get_json(f"/bitstreams/{bitstream_id}/policy")
        except (NotFoundError, UpstreamError):
            bitstream_policies = None
        access_level = (
            infer_access_level(bitstream_policies) if bitstream_policies is not None else item_access_level
        )

        self._enforce_access(access_level, allowed_levels, item_id=item_id)

        file = map_bitstream(
            bitstream, rest_base_url=self._settings.dspace_rest_base_url, access_level=access_level
        )
        return BitstreamLink(
            url=file.bitstream_link, requires_auth=access_level != "public", access_level=access_level
        )

    async def health(self) -> Health:
        try:
            await self._client.get_json("/status")
        except Exception:
            logger.warning("dspace_health_check_failed")
            return Health(status="down", detail="Không kết nối được DSpace REST.")
        return Health(status="ok")

    # --- Sprint 2-4 (chưa hiện thực) ---

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
        raise NotImplementedYetError("search_library", "Sprint 2")

    async def semantic_search(
        self,
        query: str,
        *,
        k: int = 8,
        filters: dict[str, Any] | None = None,
        allowed_levels: tuple[AccessLevel, ...] | None = None,
    ) -> list[Chunk]:
        raise NotImplementedYetError("semantic_search_documents", "Sprint 3")

    async def get_text(
        self,
        id: str,
        *,
        query: str | None = None,
        page: int | None = None,
        allowed_levels: tuple[AccessLevel, ...] | None = None,
    ) -> DocumentText:
        raise NotImplementedYetError("get_document_text/find_in_document", "Sprint 4")

    async def stats(
        self, *, group_by: list[str] | None = None, allowed_levels: tuple[AccessLevel, ...] | None = None
    ) -> Stats:
        raise NotImplementedYetError("library_stats", "Sprint 2")
