"""Ánh xạ dữ liệu DSpace 7.x REST (/server/api, HAL) -> schema chuẩn hóa.

Khác REST 6.x:
- `metadata` là DICT keyed theo field (`{"dc.title": [{"value": ...}]}`), không phải
  list phẳng `[{"key","value"}]`.
- Bitstream/mime/collection/community lấy qua object EMBED (`_embedded`) 1-shot
  (`?embed=bundles/bitstreams/format,owningCollection/parentCommunity`), không phải
  expand + nhiều request như 6.x.
- `access_level` suy từ endpoint `accessStatus` của DSpace 7 (open.access/embargo/
  restricted/metadata.only) THAY cho việc đọc resource policy (7.x cần admin/JWT mới đọc
  được policy — xem docs/DECISIONS.md). Hệ quả: 7.x chỉ phân biệt public vs non-public;
  mọi mức non-public gộp thành `restricted` (an toàn hơn — partner vẫn chỉ thấy public,
  internal vẫn thấy cả 3 mức).

Hình dạng JSON đã XÁC MINH THẬT trên https://lib.hpu.edu.vn/server/api (DSpace 7.6.5,
2026-07-14). Code vẫn phòng thủ (không crash khi thiếu field) để không vỡ khi có sai lệch nhỏ.
"""

from __future__ import annotations

import re
from typing import Any

from hpu_library_mcp.models import AccessLevel, Node, Resource, ResourceFile

# Giá trị status của DSpace 7 access-status endpoint được coi là công khai.
_OPEN_ACCESS_STATUS = "open.access"
# archivedItemsCount = -1 nghĩa "chưa tính" (lazy) trong DSpace 7 -> coi như không biết.
_COUNT_NOT_COMPUTED = -1


def access_level_from_status(status: str | None) -> AccessLevel:
    """open.access -> public; mọi trạng thái khác (embargo/restricted/metadata.only/thiếu)
    -> restricted (fail-safe, NFR-1). 7.x không suy ra được mức 'internal' từ accessStatus."""
    if status == _OPEN_ACCESS_STATUS:
        return "public"
    return "restricted"


def _first(metadata: dict[str, Any], key: str) -> str | None:
    values = metadata.get(key)
    if not values:
        return None
    value = values[0].get("value")
    return value if value else None


def _all(metadata: dict[str, Any], key: str) -> list[str]:
    return [v.get("value") for v in metadata.get(key, []) if v.get("value")]


def _parse_year(date_issued: str | None) -> int | None:
    if not date_issued:
        return None
    match = re.match(r"(\d{4})", date_issued)
    return int(match.group(1)) if match else None


def _embedded_list(container: dict[str, Any] | None, key: str) -> list[dict[str, Any]]:
    """Bóc `container._embedded[key]` (list HAL lồng nhau), an toàn khi thiếu."""
    if not container:
        return []
    return (container.get("_embedded") or {}).get(key) or []


def _count(node: dict[str, Any]) -> int | None:
    count = node.get("archivedItemsCount")
    if count is None or count == _COUNT_NOT_COMPUTED:
        return None
    return count


def map_bitstream(bitstream: dict[str, Any], *, access_level: AccessLevel) -> ResourceFile:
    fmt = (bitstream.get("_embedded") or {}).get("format") or {}
    content_link = ((bitstream.get("_links") or {}).get("content") or {}).get("href") or ""
    return ResourceFile(
        bitstream_id=str(bitstream.get("uuid") or bitstream.get("id") or ""),
        name=bitstream.get("name") or "unknown",
        mime=fmt.get("mimetype"),
        size=bitstream.get("sizeBytes"),
        bitstream_link=content_link,
        access_level=access_level,
    )


def _original_bitstreams(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Chỉ lấy bitstream bundle ORIGINAL (bỏ THUMBNAIL/TEXT/LICENSE) — nhất quán 6.x."""
    bundles = _embedded_list(item.get("_embedded", {}).get("bundles"), "bundles")
    files: list[dict[str, Any]] = []
    for bundle in bundles:
        if (bundle.get("name") or "").upper() != "ORIGINAL":
            continue
        files.extend(_embedded_list(bundle.get("_embedded", {}).get("bitstreams"), "bitstreams"))
    return files


def map_item_to_resource(
    item: dict[str, Any], *, public_base_url: str, access_status: str | None
) -> Resource:
    """Map item DSpace 7.x (đã embed bundles/format/owningCollection) -> Resource chuẩn hóa.

    `access_status` là chuỗi từ endpoint `/core/items/{uuid}/accessStatus` (adapter lấy
    riêng, không nằm trong item JSON)."""
    meta = item.get("metadata") or {}
    access_level = access_level_from_status(access_status)

    handle = item.get("handle") or ""
    url = f"{public_base_url.rstrip('/')}/handle/{handle}" if handle else None

    embedded = item.get("_embedded") or {}
    owning_collection = embedded.get("owningCollection") or {}
    collection_name = owning_collection.get("name")
    parent_community = (owning_collection.get("_embedded") or {}).get("parentCommunity") or {}
    community_name = parent_community.get("name")

    files = [
        map_bitstream(bitstream, access_level=access_level) for bitstream in _original_bitstreams(item)
    ]

    return Resource(
        id=handle or str(item.get("uuid") or ""),
        source="dspace",
        title=_first(meta, "dc.title") or item.get("name") or "(không có tiêu đề)",
        authors=_all(meta, "dc.contributor.author"),
        year=_parse_year(_first(meta, "dc.date.issued")),
        type=_first(meta, "dc.type"),
        language=_first(meta, "dc.language.iso"),
        abstract=_first(meta, "dc.description.abstract"),
        collection=collection_name,
        community=community_name,
        url=url,
        access_level=access_level,
        files=files,
        raw_meta={key: _all(meta, key) for key in meta},
    )


def map_community_to_node(community: dict[str, Any]) -> Node:
    return Node(
        id=str(community.get("uuid") or community.get("id") or ""),
        name=community.get("name") or "(không tên)",
        type="community",
        count=_count(community),
    )


def map_collection_to_node(collection: dict[str, Any]) -> Node:
    return Node(
        id=str(collection.get("uuid") or collection.get("id") or ""),
        name=collection.get("name") or "(không tên)",
        type="collection",
        count=_count(collection),
    )
