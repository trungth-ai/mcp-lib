"""Ánh xạ dữ liệu DSpace REST 6.x -> schema chuẩn hóa.

- Dublin Core -> Resource: xem 04-data-model.md §1.
- Suy diễn access_level từ resource policy: xem 05-security.md §4.
  Hình dạng JSON của /rest/items, /rest/.../policy CHƯA được xác minh trên instance
  thật (Sprint 0 chưa chạy được từ máy dev — xem docs/CLAUDE.md). Code dưới đây bám theo
  hình dạng JSON đã biết của DSpace REST 6.x (org.dspace.rest.common.Item/ResourcePolicy)
  và cố tình phòng thủ (không crash khi thiếu field) để không vỡ khi có sai lệch nhỏ.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from hpu_library_mcp.models import AccessLevel, Node, Resource, ResourceFile

# groupId của nhóm Anonymous trong DSpace — well-known mặc định là 0.
# CHƯA xác minh trên instance thật (xem 07-sprints.md Sprint 0).
ANONYMOUS_GROUP_ID = 0


def _index_metadata(metadata: list[dict[str, Any]] | None) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for entry in metadata or []:
        key = entry.get("key")
        value = entry.get("value")
        if not key or value is None:
            continue
        index.setdefault(key, []).append(value)
    return index


def _first(meta_by_key: dict[str, list[str]], key: str) -> str | None:
    values = meta_by_key.get(key)
    return values[0] if values else None


def _all(meta_by_key: dict[str, list[str]], key: str) -> list[str]:
    return meta_by_key.get(key, [])


def _parse_year(date_issued: str | None) -> int | None:
    if not date_issued:
        return None
    match = re.match(r"(\d{4})", date_issued)
    return int(match.group(1)) if match else None


def _policy_is_active(policy: dict[str, Any], *, today: date | None = None) -> bool:
    """True nếu policy đang trong hiệu lực (không phải embargo tương lai / đã hết hạn)."""
    today = today or datetime.now().date()
    for field, cmp in (("startDate", lambda d: d > today), ("endDate", lambda d: d < today)):
        raw = policy.get(field)
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(str(raw)[:10]).date()
        except ValueError:
            continue  # định dạng lạ -> bỏ qua thay vì crash, không coi là hết hạn/embargo
        if cmp(parsed):
            return False
    return True


def infer_access_level(resource_policies: list[dict[str, Any]] | None) -> AccessLevel:
    """Suy diễn access_level từ resource policy.

    - Anonymous READ (đang hiệu lực) -> public
    - READ khác (nhóm nội bộ) -> internal
    - Không có READ nào / dữ liệu thiếu/mơ hồ -> restricted (fail-safe, NFR-1 bắt buộc)
    """
    if not resource_policies:
        return "restricted"

    read_policies = [p for p in resource_policies if (p.get("action") or "").upper() == "READ"]
    active_read_policies = [p for p in read_policies if _policy_is_active(p)]
    if not active_read_policies:
        return "restricted"

    if any(p.get("groupId") == ANONYMOUS_GROUP_ID for p in active_read_policies):
        return "public"

    return "internal"


def map_bitstream(
    bitstream: dict[str, Any], *, rest_base_url: str, access_level: AccessLevel
) -> ResourceFile:
    retrieve_link = bitstream.get("retrieveLink") or ""
    link = (
        retrieve_link
        if retrieve_link.startswith("http")
        else f"{rest_base_url.rstrip('/')}{retrieve_link}"
    )
    return ResourceFile(
        bitstream_id=str(bitstream.get("uuid") or bitstream.get("id") or ""),
        name=bitstream.get("name") or "unknown",
        mime=bitstream.get("mimeType"),
        size=bitstream.get("sizeBytes"),
        bitstream_link=link,
        access_level=access_level,
    )


def map_item_to_resource(
    item: dict[str, Any],
    *,
    rest_base_url: str,
    public_base_url: str,
    resource_policies: list[dict[str, Any]] | None = None,
    bitstream_policies: dict[str, list[dict[str, Any]]] | None = None,
) -> Resource:
    """Map item DSpace REST 6.x (expand=metadata,bitstreams,...) -> Resource chuẩn hóa."""
    meta = _index_metadata(item.get("metadata"))
    item_access_level = infer_access_level(resource_policies)

    handle = item.get("handle") or item.get("uuid") or ""
    url = f"{public_base_url.rstrip('/')}/handle/{handle}" if handle else None

    parent_collection = item.get("parentCollection") or {}
    parent_communities = item.get("parentCommunityList") or []
    community_name = parent_communities[0].get("name") if parent_communities else None

    files: list[ResourceFile] = []
    for bitstream in item.get("bitstreams") or []:
        bundle = (bitstream.get("bundleName") or "").upper()
        if bundle and bundle != "ORIGINAL":
            continue  # bỏ qua bundle phụ (LICENSE, TEXT, THUMBNAIL...)
        bitstream_id = str(bitstream.get("uuid") or bitstream.get("id") or "")
        policies = (bitstream_policies or {}).get(bitstream_id)
        # Chưa lấy được policy riêng của bitstream -> kế thừa mức của item (fail-safe).
        bitstream_access = infer_access_level(policies) if policies is not None else item_access_level
        files.append(map_bitstream(bitstream, rest_base_url=rest_base_url, access_level=bitstream_access))

    return Resource(
        id=handle or str(item.get("uuid") or ""),
        source="dspace",
        title=_first(meta, "dc.title") or "(không có tiêu đề)",
        authors=_all(meta, "dc.contributor.author"),
        year=_parse_year(_first(meta, "dc.date.issued")),
        type=_first(meta, "dc.type"),
        language=_first(meta, "dc.language.iso"),
        abstract=_first(meta, "dc.description.abstract"),
        collection=parent_collection.get("name"),
        community=community_name,
        url=url,
        access_level=item_access_level,
        files=files,
        raw_meta=dict(meta),
    )


def extract_sort_date(item: dict[str, Any]) -> str:
    """Ngày dùng để sắp 'mới nhất' cho get_recent_items (accessioned ưu tiên, fallback issued)."""
    meta = _index_metadata(item.get("metadata"))
    return _first(meta, "dc.date.accessioned") or _first(meta, "dc.date.issued") or ""


def map_community_to_node(community: dict[str, Any]) -> Node:
    return Node(
        id=str(community.get("uuid") or community.get("id") or ""),
        name=community.get("name") or "(không tên)",
        type="community",
        count=community.get("countItems"),
    )


def map_collection_to_node(collection: dict[str, Any]) -> Node:
    return Node(
        id=str(collection.get("uuid") or collection.get("id") or ""),
        name=collection.get("name") or "(không tên)",
        type="collection",
        count=collection.get("numberItems") if "numberItems" in collection else collection.get("countItems"),
    )
