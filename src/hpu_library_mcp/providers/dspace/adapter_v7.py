"""DSpace7Adapter — REST 7.x (`/server/api`, HAL) + Discovery tích hợp, xem adapter_base.py.

Toàn bộ chi tiết đường REST 7.x / hình dạng HAL / cú pháp Discovery nằm ở đây. Trả về
object ĐÃ CHUẨN HÓA (`Resource`/`Node`/`ResourceFile`) y hệt DSpace6Adapter — `DSpaceProvider`
KHÔNG cần biết đang nói chuyện với 6.3 hay 7.6 (NFR-4). Chọn adapter theo
`Settings.dspace_version` trong provider._build_default_adapter().

Khác 6.3:
- 1 base URL duy nhất (`/server/api`) — Discovery là 1 nhánh REST (`/discover/...`),
  KHÔNG gọi Solr trực tiếp.
- Search có sort theo ngày native (`sort=dc.date.accessioned,DESC`) -> `get_recent_items`
  KHÔNG cần over-fetch + sort phía client như 6.3.
- `access_level` suy từ endpoint `accessStatus` (public vs non-public; xem mapping_v7.py).
- `scope` (metadata/fulltext/both) của tool bị BỎ QUA: Discovery 7.x luôn tìm cả metadata
  lẫn full-text bằng 1 tham số `query`; highlight lấy từ `hitHighlights` của mỗi hit.
"""

from __future__ import annotations

from typing import Any

from hpu_library_mcp.config import Settings
from hpu_library_mcp.errors import NotFoundError, UpstreamError
from hpu_library_mcp.logging_setup import get_logger
from hpu_library_mcp.models import Health, Node, Resource, ResourceFile
from hpu_library_mcp.providers.dspace.adapter_base import DSpaceAdapter
from hpu_library_mcp.providers.dspace.client_v7 import DSpace7Client
from hpu_library_mcp.providers.dspace.mapping_v7 import (
    _original_bitstreams,
    access_level_from_status,
    map_bitstream,
    map_collection_to_node,
    map_community_to_node,
    map_item_to_resource,
)

logger = get_logger(__name__)

# Số node (community/collection) tối đa lấy 1 trang — đủ cho cây phân cấp thư viện HPU.
_NODE_PAGE_SIZE = 100
# Số giá trị facet lấy cho library_stats (group_by).
_STATS_FACET_SIZE = 50


def _dig(data: Any, *keys: str, default: Any = None) -> Any:
    """Đi sâu qua chuỗi key dict lồng nhau (HAL `_embedded`), an toàn khi thiếu."""
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return current if current is not None else default


class DSpace7Adapter(DSpaceAdapter):
    def __init__(self, *, client: DSpace7Client, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    async def aclose(self) -> None:
        await self._client.aclose()

    # --- helpers nội bộ REST 7.x ---

    async def _fetch_item(self, id: str) -> dict[str, Any]:
        """Lấy item (kèm embed bundles/format/collection) theo uuid HOẶC handle."""
        uuid = id
        if "/" in id:  # dạng handle "123456789/42" -> resolve qua /pid/find (follow redirect)
            resolved = await self._client.get_json("/pid/find", params={"id": id})
            if not resolved or resolved.get("type") != "item":
                raise NotFoundError("Không tìm thấy tài liệu trong hệ thống thư viện.")
            uuid = str(resolved.get("uuid") or "")
        item = await self._client.get_json(
            f"/core/items/{uuid}", params={"embed": self._settings.dspace7_item_embed}
        )
        if not item:
            raise NotFoundError("Không tìm thấy tài liệu trong hệ thống thư viện.")
        return item

    async def _fetch_access_status(self, uuid: str | None) -> str | None:
        if not uuid:
            return None
        try:
            data = await self._client.get_json(f"/core/items/{uuid}/accessStatus")
        except (NotFoundError, UpstreamError):
            return None  # -> access_level restricted (fail-safe)
        return (data or {}).get("status")

    def _facet_field_map(self) -> dict[str, str]:
        """Tên facet LOGIC (tool) -> tên facet Discovery 7.x (config). "" = không khả dụng."""
        s = self._settings
        return {"type": s.dspace7_facet_type, "year": s.dspace7_facet_year, "author": s.dspace7_facet_author}

    def _discovery_filter_params(
        self, *, query: str | None, filters: dict[str, Any] | None
    ) -> list[tuple[str, Any]]:
        """Xây phần query + filter dùng CHUNG cho search và facet (không kèm page/size/sort)."""
        filters = filters or {}
        params: list[tuple[str, Any]] = [("dsoType", "item")]
        if query:
            params.append(("query", query))

        # collection/community -> scope (1 container uuid). Ưu tiên collection nếu có cả hai.
        scope = filters.get("collection") or filters.get("community")
        if scope:
            params.append(("scope", str(scope)))

        facet_map = self._facet_field_map()
        for filter_key in ("author", "type"):
            value = filters.get(filter_key)
            ds_facet = facet_map.get(filter_key)
            if value and ds_facet:
                params.append((f"f.{ds_facet}", f"{value},equals"))

        year_from = filters.get("year_from")
        year_to = filters.get("year_to")
        if (year_from is not None or year_to is not None) and self._settings.dspace7_facet_year:
            lo = year_from if year_from is not None else "*"
            hi = year_to if year_to is not None else "*"
            params.append((f"f.{self._settings.dspace7_facet_year}", f"[{lo} TO {hi}],equals"))

        return params

    async def _fetch_facet_values(
        self, ds_facet: str, base_params: list[tuple[str, Any]], *, size: int, anonymous: bool
    ) -> dict[str, int]:
        try:
            data = await self._client.get_json(
                f"/discover/facets/{ds_facet}", params=[*base_params, ("size", size)], anonymous=anonymous
            )
        except UpstreamError:
            logger.warning("dspace7_facet_fetch_failed facet=%s", ds_facet)
            return {}
        values = _dig(data, "_embedded", "values", default=[])
        return {v.get("label"): int(v.get("count") or 0) for v in values if v.get("label")}

    # --- DSpaceAdapter ---

    async def resolve_item(self, id: str) -> Resource:
        item = await self._fetch_item(id)
        status = await self._fetch_access_status(item.get("uuid"))
        return map_item_to_resource(
            item, public_base_url=self._settings.dspace_public_base_url, access_status=status
        )

    async def list_communities(self, *, parent: str | None) -> list[Node]:
        if parent:
            path, key = f"/core/communities/{parent}/subcommunities", "subcommunities"
        else:
            path, key = "/core/communities/search/top", "communities"
        data = await self._client.get_json(path, params={"size": _NODE_PAGE_SIZE})
        raw = _dig(data, "_embedded", key, default=[])
        return [map_community_to_node(c) for c in raw]

    async def list_collections(self, *, parent: str | None) -> list[Node]:
        path = f"/core/communities/{parent}/collections" if parent else "/core/collections"
        data = await self._client.get_json(path, params={"size": _NODE_PAGE_SIZE})
        raw = _dig(data, "_embedded", "collections", default=[])
        return [map_collection_to_node(c) for c in raw]

    async def list_recent_candidates(self, *, collection: str | None, limit: int) -> list[Resource]:
        # DSpace 7 hỗ trợ sort native -> lấy đúng `limit` item mới nhất, không over-fetch.
        params: list[tuple[str, Any]] = [
            ("dsoType", "item"),
            ("sort", "dc.date.accessioned,DESC"),
            ("page", 0),
            ("size", limit),
        ]
        if collection:
            params.append(("scope", collection))
        data = await self._client.get_json("/discover/search/objects", params=params)
        objects = _dig(data, "_embedded", "searchResult", "_embedded", "objects", default=[])

        resources: list[Resource] = []
        for obj in objects[:limit]:
            io = _dig(obj, "_embedded", "indexableObject", default={})
            status = await self._fetch_access_status(io.get("uuid"))
            resources.append(
                map_item_to_resource(
                    io, public_base_url=self._settings.dspace_public_base_url, access_status=status
                )
            )
        return resources

    async def get_bitstream(self, item_id: str, bitstream_id: str) -> ResourceFile:
        item = await self._fetch_item(item_id)
        status = await self._fetch_access_status(item.get("uuid"))
        access_level = access_level_from_status(status)

        bitstream = next(
            (
                b
                for b in _original_bitstreams(item)
                if str(b.get("uuid") or b.get("id") or "") == bitstream_id
            ),
            None,
        )
        if bitstream is None:
            raise NotFoundError("Không tìm thấy tệp trong tài liệu này.")
        return map_bitstream(bitstream, access_level=access_level)

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
        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        base_params = self._discovery_filter_params(query=query, filters=filters)
        search_params = [*base_params, ("page", page - 1), ("size", page_size)]

        data = await self._client.get_json("/discover/search/objects", params=search_params)
        search_result = _dig(data, "_embedded", "searchResult", default={})
        total = int(_dig(search_result, "page", "totalElements", default=0))
        objects = _dig(search_result, "_embedded", "objects", default=[])

        hits: list[tuple[str, list[str]]] = []
        for obj in objects:
            io = _dig(obj, "_embedded", "indexableObject", default={})
            # Trả uuid cho provider (get() sau đó lấy lại metadata + access_level chính xác);
            # Resource.id map ra vẫn là handle nên citations/URL không bị ảnh hưởng.
            ident = io.get("uuid") or io.get("handle")
            if not ident:
                continue
            snippets: list[str] = []
            for field_snippets in (obj.get("hitHighlights") or {}).values():
                snippets.extend(field_snippets or [])
            hits.append((str(ident), snippets))

        facets_out: dict[str, dict[str, int]] = {}
        facet_map = self._facet_field_map()
        for name in facets or []:
            ds_facet = facet_map.get(name)
            if not ds_facet:
                continue  # facet không khả dụng trên instance này (vd "type") -> bỏ qua an toàn
            values = await self._fetch_facet_values(
                ds_facet, base_params, size=page_size * 2, anonymous=False
            )
            if values:
                facets_out[name] = values

        return total, hits, facets_out

    async def stats_facets(
        self, *, group_by: list[str], allowed_levels: tuple[str, ...] | None
    ) -> tuple[int, dict[str, dict[str, int]]]:
        # partner (chỉ thấy public) -> gọi Discovery ẩn danh để DSpace tự lọc theo quyền đọc
        # Anonymous (thay cho `fq=read:g0` của Solr 6.x — xem docs/DECISIONS.md).
        anonymous = allowed_levels is not None and set(allowed_levels) == {"public"}
        base_params: list[tuple[str, Any]] = [("dsoType", "item")]

        data = await self._client.get_json(
            "/discover/search/objects", params=[*base_params, ("size", 1)], anonymous=anonymous
        )
        total = int(_dig(data, "_embedded", "searchResult", "page", "totalElements", default=0))

        facet_map = self._facet_field_map()
        by: dict[str, dict[str, int]] = {}
        for name in group_by:
            ds_facet = facet_map.get(name) or ({"collection": "", "community": ""}).get(name)
            if not ds_facet:
                continue  # facet không khả dụng -> bỏ qua an toàn (không trả số 0 gây hiểu nhầm)
            values = await self._fetch_facet_values(
                ds_facet, base_params, size=_STATS_FACET_SIZE, anonymous=anonymous
            )
            if values:
                by[name] = values
        return total, by

    async def health(self) -> Health:
        try:
            await self._client.get_json("/authn/status")
        except Exception:
            logger.warning("dspace7_health_check_failed")
            return Health(status="down", detail="Không kết nối được DSpace REST (/server/api).")
        return Health(status="ok")
