"""DSpace6Adapter — REST 6.3 (`/rest`) + Solr Discovery cụ thể, xem adapter_base.py.

Toàn bộ chi tiết đường REST/field Solr nằm ở đây (chuyển nguyên từ provider.py khi tách
Sprint "fix gaps" — xem docs/DECISIONS.md). `DSpaceProvider` không import module này
trực tiếp cho logic, chỉ gọi qua interface `DSpaceAdapter`.
"""

from __future__ import annotations

from typing import Any

from hpu_library_mcp.config import Settings
from hpu_library_mcp.errors import NotFoundError, SolrBadRequestError, UpstreamError
from hpu_library_mcp.logging_setup import get_logger
from hpu_library_mcp.models import Health, Node, Resource, ResourceFile
from hpu_library_mcp.providers.dspace.adapter_base import DSpaceAdapter
from hpu_library_mcp.providers.dspace.client import DSpaceRestClient
from hpu_library_mcp.providers.dspace.mapping import (
    extract_sort_date,
    infer_access_level,
    map_bitstream,
    map_collection_to_node,
    map_community_to_node,
    map_item_to_resource,
)
from hpu_library_mcp.providers.dspace.solr_client import SolrClient
from hpu_library_mcp.providers.dspace.solr_search import (
    build_search_params,
    facet_field_names,
    parse_facet_stats_response,
    parse_search_response,
    strip_highlighting_params,
)

logger = get_logger(__name__)

_ITEM_EXPAND = "metadata,bitstreams,parentCollection,parentCommunityList"
# Số item tối đa tải để sắp xếp lấy "mới nhất" khi REST 6.x không hỗ trợ sort theo ngày trực tiếp.
_RECENT_ITEMS_OVERFETCH_CAP = 200


class DSpace6Adapter(DSpaceAdapter):
    def __init__(self, *, client: DSpaceRestClient, solr_client: SolrClient, settings: Settings) -> None:
        self._client = client
        self._solr = solr_client
        self._settings = settings

    async def aclose(self) -> None:
        await self._client.aclose()
        await self._solr.aclose()

    # --- helpers nội bộ REST 6.x ---

    async def _resolve_raw_item(self, id: str) -> dict[str, Any]:
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

    def _map_item(self, item: dict[str, Any], policies: list[dict[str, Any]] | None) -> Resource:
        return map_item_to_resource(
            item,
            rest_base_url=self._settings.dspace_rest_base_url,
            public_base_url=self._settings.dspace_public_base_url,
            resource_policies=policies,
        )

    # --- DSpaceAdapter ---

    async def resolve_item(self, id: str) -> Resource:
        item = await self._resolve_raw_item(id)
        policies = await self._get_item_policies(item.get("uuid"))
        return self._map_item(item, policies)

    async def list_communities(self, *, parent: str | None) -> list[Node]:
        path = f"/communities/{parent}/communities" if parent else "/communities/top-communities"
        raw = await self._client.get_json(path) or []
        return [map_community_to_node(c) for c in raw]

    async def list_collections(self, *, parent: str | None) -> list[Node]:
        path = f"/communities/{parent}/collections" if parent else "/collections"
        raw = await self._client.get_json(path) or []
        return [map_collection_to_node(c) for c in raw]

    async def list_recent_candidates(self, *, collection: str | None, limit: int) -> list[Resource]:
        # REST 6.x không đảm bảo thứ tự theo ngày -> tải dư rồi sort phía client.
        fetch_n = min(max(limit * 5, 50), _RECENT_ITEMS_OVERFETCH_CAP)
        path = f"/collections/{collection}/items" if collection else "/items"
        raw_items = await self._client.get_json(path, params={"limit": fetch_n, "expand": "metadata"}) or []
        raw_items_sorted = sorted(raw_items, key=extract_sort_date, reverse=True)[:limit]

        resources: list[Resource] = []
        for raw_item in raw_items_sorted:
            policies = await self._get_item_policies(raw_item.get("uuid"))
            resources.append(self._map_item(raw_item, policies))
        return resources

    async def get_bitstream(self, item_id: str, bitstream_id: str) -> ResourceFile:
        item = await self._resolve_raw_item(item_id)
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
        return map_bitstream(
            bitstream, rest_base_url=self._settings.dspace_rest_base_url, access_level=access_level
        )

    async def download_bitstream_bytes(self, file: ResourceFile) -> bytes:
        return await self._client.get_bytes(file.bitstream_link)

    async def search_candidates(
        self,
        *,
        query: str,
        scope: str,
        filters: dict[str, Any] | None,
        facets: list[str] | None,
        page: int,
        page_size: int,
    ) -> tuple[int, list[tuple[str, list[str]]], dict[str, dict[str, int]]]:
        settings = self._settings
        params = build_search_params(
            query=query,
            scope=scope,
            filters=filters,
            facets=facets,
            page=page,
            page_size=page_size,
            default_field=settings.dspace_solr_field_default,
            fulltext_field=settings.dspace_solr_fulltext_field,
            handle_field=settings.dspace_solr_field_handle,
            resourcetype_field=settings.dspace_solr_field_resourcetype,
            resourcetype_item_value=settings.dspace_solr_resourcetype_item,
            collection_field=settings.dspace_solr_field_collection,
            community_field=settings.dspace_solr_field_community,
            year_field=settings.dspace_solr_field_year,
            type_field=settings.dspace_solr_field_type,
            author_field=settings.dspace_solr_field_author,
        )

        try:
            raw = await self._solr.select(params)
        except SolrBadRequestError:
            if any(str(key).startswith("hl") for key, _ in params):
                # Field full-text có thể sai tên/chưa index -> suy biến: bỏ highlight, thử lại.
                logger.warning("solr_search_degraded_no_highlight")
                raw = await self._solr.select(strip_highlighting_params(params))
            else:
                raise

        total, hits, raw_facets = parse_search_response(raw, handle_field=settings.dspace_solr_field_handle)

        field_to_facet_name = {
            field: name
            for name, field in facet_field_names(
                type_field=settings.dspace_solr_field_type,
                year_field=settings.dspace_solr_field_year,
                author_field=settings.dspace_solr_field_author,
            ).items()
        }
        facets_out = {field_to_facet_name.get(field, field): counts for field, counts in raw_facets.items()}
        return total, hits, facets_out

    async def stats_facets(
        self, *, group_by: list[str], allowed_levels: tuple[str, ...] | None
    ) -> tuple[int, dict[str, dict[str, int]]]:
        settings = self._settings
        field_map = {
            **facet_field_names(
                type_field=settings.dspace_solr_field_type,
                year_field=settings.dspace_solr_field_year,
                author_field=settings.dspace_solr_field_author,
            ),
            "collection": settings.dspace_solr_field_collection,
        }

        params: list[tuple[str, Any]] = [
            ("q", "*:*"),
            ("rows", 0),
            ("fq", f"{settings.dspace_solr_field_resourcetype}:{settings.dspace_solr_resourcetype_item}"),
            ("facet", "true"),
        ]
        # Không có REST hậu kiểm từng item như search_candidates (stats là facet COUNT) ->
        # lọc thẳng ở Solr qua field `read` khi key chỉ được thấy public.
        if allowed_levels is not None and set(allowed_levels) == {"public"}:
            params.append(("fq", f"{settings.dspace_solr_field_read}:{settings.dspace_solr_anonymous_read_token}"))

        requested: list[tuple[str, str]] = []
        for name in group_by:
            field = field_map.get(name)
            if field:
                params.append(("facet.field", field))
                requested.append((name, field))

        raw = await self._solr.select(params)
        total, raw_facets = parse_facet_stats_response(raw)

        by = {name: raw_facets[field] for name, field in requested if field in raw_facets}
        return total, by

    async def health(self) -> Health:
        try:
            await self._client.get_json("/status")
        except Exception:
            logger.warning("dspace_health_check_failed")
            return Health(status="down", detail="Không kết nối được DSpace REST.")
        return Health(status="ok")
