"""Xây query & diễn giải kết quả Solr Discovery cho search_library/library_stats.

Tách khỏi solr_client.py (chỉ gửi HTTP) và provider.py (điều phối + gọi REST) để test
độc lập, không cần Settings/HTTP thật.
"""

from __future__ import annotations

import re
from typing import Any

_LUCENE_SPECIAL_CHARS = re.compile(r'([+\-!(){}\[\]^"~*?:\\/&|])')


def escape_solr_value(text: str) -> str:
    """Escape ký tự đặc biệt Lucene/Solr trong giá trị tự do (không đụng dấu tiếng Việt)."""
    if not text:
        return text
    return _LUCENE_SPECIAL_CHARS.sub(r"\\\1", text)


def build_search_params(
    *,
    query: str,
    scope: str,
    filters: dict[str, Any] | None,
    facets: list[str] | None,
    page: int,
    page_size: int,
    default_field: str,
    fulltext_field: str,
    handle_field: str,
    resourcetype_field: str,
    resourcetype_item_value: str,
    collection_field: str,
    community_field: str,
    year_field: str,
    type_field: str,
    author_field: str,
) -> list[tuple[str, Any]]:
    filters = filters or {}
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    df = fulltext_field if scope == "fulltext" else default_field

    params: list[tuple[str, Any]] = [
        ("q", escape_solr_value(query) if query else "*:*"),
        ("df", df),
        ("start", (page - 1) * page_size),
        ("rows", page_size),
        ("fl", f"{handle_field},score"),
        ("fq", f"{resourcetype_field}:{resourcetype_item_value}"),
    ]

    for filter_key, field in (("collection", collection_field), ("community", community_field), ("type", type_field), ("author", author_field)):
        value = filters.get(filter_key)
        if value:
            params.append(("fq", f'{field}:"{escape_solr_value(str(value))}"'))

    year_from = filters.get("year_from")
    year_to = filters.get("year_to")
    if year_from is not None or year_to is not None:
        lo = year_from if year_from is not None else "*"
        hi = year_to if year_to is not None else "*"
        params.append(("fq", f"{year_field}:[{lo} TO {hi}]"))

    facet_field_map = facet_field_names(type_field=type_field, year_field=year_field, author_field=author_field)
    requested_facets = [f for f in (facets or []) if f in facet_field_map]
    if requested_facets:
        params.append(("facet", "true"))
        for facet_name in requested_facets:
            params.append(("facet.field", facet_field_map[facet_name]))

    if scope in ("fulltext", "both"):
        params.extend(
            [
                ("hl", "true"),
                ("hl.fl", fulltext_field),
                ("hl.simple.pre", "<em>"),
                ("hl.simple.post", "</em>"),
                ("hl.fragsize", 200),
            ]
        )

    return params


def facet_field_names(*, type_field: str, year_field: str, author_field: str) -> dict[str, str]:
    return {"type": type_field, "year": year_field, "author": author_field}


def strip_highlighting_params(params: list[tuple[str, Any]]) -> list[tuple[str, Any]]:
    """Bỏ mọi tham số hl.* — dùng khi suy biến do field full-text sai tên/chưa index."""
    return [(k, v) for k, v in params if not str(k).startswith("hl")]


def _parse_facet_fields(raw: dict[str, Any]) -> dict[str, dict[str, int]]:
    facet_counts_raw = ((raw.get("facet_counts") or {}).get("facet_fields")) or {}
    facets: dict[str, dict[str, int]] = {}
    for field_name, flat_list in facet_counts_raw.items():
        counts: dict[str, int] = {}
        for i in range(0, len(flat_list) - 1, 2):
            counts[str(flat_list[i])] = int(flat_list[i + 1])
        facets[field_name] = counts
    return facets


def parse_search_response(
    raw: dict[str, Any], *, handle_field: str
) -> tuple[int, list[tuple[str, list[str]]], dict[str, dict[str, int]]]:
    """Trả (total, [(handle, highlight_snippets)], facets thô theo TÊN FIELD Solr gốc).

    Ghép highlight theo VỊ TRÍ (không theo key của dict `highlighting`, vì uniqueKey thật
    của Solr core này chưa xác minh) — an toàn vì việc ghép sai vị trí chỉ ảnh hưởng hiển
    thị đoạn trích, không ảnh hưởng phân quyền (access_level luôn tính lại qua REST ở
    provider.py, không dựa vào dữ liệu Solr).
    """
    response_section = raw.get("response") or {}
    total = int(response_section.get("numFound") or 0)
    docs = response_section.get("docs") or []

    highlighting = raw.get("highlighting") or {}
    highlight_values = list(highlighting.values())
    highlights_reliable = len(highlight_values) == len(docs)

    results: list[tuple[str, list[str]]] = []
    for index, doc in enumerate(docs):
        handle = doc.get(handle_field)
        if not handle:
            continue  # thiếu field định danh đã cấu hình -> bỏ qua an toàn, không đoán
        snippets: list[str] = []
        if highlights_reliable:
            entry = highlight_values[index] or {}
            for field_snippets in entry.values():
                snippets.extend(field_snippets)
        results.append((handle, snippets))

    facets = _parse_facet_fields(raw)
    return total, results, facets


def parse_facet_stats_response(raw: dict[str, Any]) -> tuple[int, dict[str, dict[str, int]]]:
    """Dùng cho library_stats: total_items (numFound) + facet_counts thô theo field Solr."""
    total = int(((raw.get("response") or {}).get("numFound")) or 0)
    return total, _parse_facet_fields(raw)
