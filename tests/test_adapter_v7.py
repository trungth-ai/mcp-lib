"""Test DSpace7Adapter (adapter_v7.py) qua respx — dựng client_v7 thật, mock HTTP.

Bám hình dạng Discovery/HAL thật của https://lib.hpu.edu.vn/server/api (2026-07-14).
Kiểm cả tích hợp qua DSpaceProvider để chắc chắn enforce quyền chạy đúng trên adapter v7.
"""

from __future__ import annotations

from typing import Any

import httpx
import respx

from hpu_library_mcp.config import Settings
from hpu_library_mcp.providers.dspace.adapter_v7 import DSpace7Adapter
from hpu_library_mcp.providers.dspace.client_v7 import DSpace7Client
from hpu_library_mcp.providers.dspace.provider import DSpaceProvider

BASE = "https://lib.hpu.edu.vn/server/api"


def _settings(**overrides: Any) -> Settings:
    base = {"dspace_version": "7.6", "dspace7_api_base_url": BASE, "dspace_public_base_url": "https://lib.hpu.edu.vn"}
    base.update(overrides)
    return Settings(**base)


def _make_adapter(**overrides: Any) -> DSpace7Adapter:
    settings = _settings(**overrides)
    client = DSpace7Client(base_url=settings.dspace7_api_base_url)
    return DSpace7Adapter(client=client, settings=settings)


def _hal_item(uuid: str = "u1", handle: str = "123456789/42", title: str = "Tài liệu A") -> dict[str, Any]:
    return {
        "uuid": uuid,
        "handle": handle,
        "metadata": {
            "dc.title": [{"value": title}],
            "dc.contributor.author": [{"value": "Nguyễn Văn A"}],
            "dc.date.issued": [{"value": "2023"}],
        },
        "_embedded": {"owningCollection": {"name": "Bộ sưu tập X"}, "bundles": {"_embedded": {"bundles": []}}},
    }


def _search_objects(items: list[dict[str, Any]], total: int | None = None) -> dict[str, Any]:
    objects = [
        {"hitHighlights": {"dc.title": [f"<em>{io['metadata']['dc.title'][0]['value']}</em>"]},
         "_embedded": {"indexableObject": io}}
        for io in items
    ]
    return {
        "_embedded": {
            "searchResult": {
                "page": {"totalElements": total if total is not None else len(items)},
                "_embedded": {"objects": objects},
            }
        }
    }


def _facet_values(pairs: list[tuple[str, int]]) -> dict[str, Any]:
    return {"_embedded": {"values": [{"label": label, "count": count} for label, count in pairs]}}


# --- resolve_item ---


@respx.mock
async def test_resolve_item_by_uuid():
    respx.get(f"{BASE}/core/items/u1").mock(return_value=httpx.Response(200, json=_hal_item()))
    respx.get(f"{BASE}/core/items/u1/accessStatus").mock(
        return_value=httpx.Response(200, json={"status": "open.access"})
    )
    adapter = _make_adapter()
    try:
        resource = await adapter.resolve_item("u1")
    finally:
        await adapter.aclose()
    assert resource.access_level == "public"
    assert resource.id == "123456789/42"
    assert resource.collection == "Bộ sưu tập X"


@respx.mock
async def test_resolve_item_by_handle_resolves_via_pid_find():
    respx.get(f"{BASE}/pid/find").mock(
        return_value=httpx.Response(200, json={"type": "item", "uuid": "u1"})
    )
    respx.get(f"{BASE}/core/items/u1").mock(return_value=httpx.Response(200, json=_hal_item()))
    respx.get(f"{BASE}/core/items/u1/accessStatus").mock(
        return_value=httpx.Response(200, json={"status": "restricted"})
    )
    adapter = _make_adapter()
    try:
        resource = await adapter.resolve_item("123456789/42")
    finally:
        await adapter.aclose()
    assert resource.access_level == "restricted"


@respx.mock
async def test_resolve_item_access_status_failure_is_restricted_failsafe():
    respx.get(f"{BASE}/core/items/u1").mock(return_value=httpx.Response(200, json=_hal_item()))
    respx.get(f"{BASE}/core/items/u1/accessStatus").mock(return_value=httpx.Response(500))
    adapter = _make_adapter()
    try:
        resource = await adapter.resolve_item("u1")
    finally:
        await adapter.aclose()
    assert resource.access_level == "restricted"


# --- list communities / collections ---


@respx.mock
async def test_list_top_communities():
    respx.get(f"{BASE}/core/communities/search/top").mock(
        return_value=httpx.Response(
            200,
            json={"_embedded": {"communities": [{"uuid": "c1", "name": "English resources", "archivedItemsCount": -1}]}},
        )
    )
    adapter = _make_adapter()
    try:
        nodes = await adapter.list_communities(parent=None)
    finally:
        await adapter.aclose()
    assert [n.name for n in nodes] == ["English resources"]
    assert nodes[0].type == "community"
    assert nodes[0].count is None


@respx.mock
async def test_list_collections_of_community():
    respx.get(f"{BASE}/core/communities/c1/collections").mock(
        return_value=httpx.Response(
            200, json={"_embedded": {"collections": [{"uuid": "col1", "name": "Giáo trình"}]}}
        )
    )
    adapter = _make_adapter()
    try:
        nodes = await adapter.list_collections(parent="c1")
    finally:
        await adapter.aclose()
    assert nodes[0].id == "col1"
    assert nodes[0].type == "collection"


# --- recent (native sort) ---


@respx.mock
async def test_list_recent_candidates_uses_native_sort_no_overfetch():
    items = [_hal_item("u1", "1/a", "Mới nhất"), _hal_item("u2", "1/b", "Cũ hơn")]
    route = respx.get(f"{BASE}/discover/search/objects").mock(
        return_value=httpx.Response(200, json=_search_objects(items))
    )
    respx.get(f"{BASE}/core/items/u1/accessStatus").mock(
        return_value=httpx.Response(200, json={"status": "open.access"})
    )
    respx.get(f"{BASE}/core/items/u2/accessStatus").mock(
        return_value=httpx.Response(200, json={"status": "open.access"})
    )
    adapter = _make_adapter()
    try:
        resources = await adapter.list_recent_candidates(collection=None, limit=2)
    finally:
        await adapter.aclose()
    assert [r.title for r in resources] == ["Mới nhất", "Cũ hơn"]
    # sort đẩy xuống server -> tham số sort giảm dần theo ngày accession (dấu phẩy được URL-encode)
    url = str(route.calls.last.request.url)
    assert "sort=dc.date.accessioned" in url and "DESC" in url


# --- search + facets ---


@respx.mock
async def test_search_candidates_returns_uuid_highlights_and_maps_facets():
    items = [_hal_item("u1", "1/a", "Giáo trình A"), _hal_item("u2", "1/b", "Giáo trình B")]
    respx.get(f"{BASE}/discover/search/objects").mock(
        return_value=httpx.Response(200, json=_search_objects(items, total=42))
    )
    respx.get(f"{BASE}/discover/facets/author").mock(
        return_value=httpx.Response(200, json=_facet_values([("Nguyễn Văn A", 10)]))
    )
    respx.get(f"{BASE}/discover/facets/dateIssued").mock(
        return_value=httpx.Response(200, json=_facet_values([("2023", 7)]))
    )
    adapter = _make_adapter()
    try:
        total, hits, facets = await adapter.search_candidates(
            query="giáo trình", scope="both", filters=None, facets=["author", "year", "type"], page=1, page_size=10
        )
    finally:
        await adapter.aclose()
    assert total == 42
    assert [h[0] for h in hits] == ["u1", "u2"]  # trả uuid cho provider.get()
    assert hits[0][1] == ["<em>Giáo trình A</em>"]
    assert facets["author"] == {"Nguyễn Văn A": 10}
    assert facets["year"] == {"2023": 7}
    assert "type" not in facets  # facet type không cấu hình trên instance HPU -> bỏ qua an toàn


@respx.mock
async def test_search_candidates_builds_scope_and_filter_params():
    captured = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=_search_objects([]))

    respx.get(f"{BASE}/discover/search/objects").mock(side_effect=_capture)
    adapter = _make_adapter()
    try:
        await adapter.search_candidates(
            query="x",
            scope="metadata",
            filters={"collection": "col-uuid", "author": "Nguyễn Văn A", "year_from": 2015, "year_to": 2020},
            facets=None,
            page=2,
            page_size=5,
        )
    finally:
        await adapter.aclose()
    url = captured["url"]
    assert "scope=col-uuid" in url
    assert "f.author=" in url
    assert "f.dateIssued=" in url
    assert "page=1" in url  # page 2 (1-based) -> DSpace page=1 (0-based)


# --- stats + partner anonymous filtering ---


@respx.mock
async def test_stats_facets_returns_total_and_grouped_counts():
    respx.get(f"{BASE}/discover/search/objects").mock(
        return_value=httpx.Response(200, json=_search_objects([], total=32268))
    )
    respx.get(f"{BASE}/discover/facets/dateIssued").mock(
        return_value=httpx.Response(200, json=_facet_values([("2023", 100), ("2022", 90)]))
    )
    adapter = _make_adapter()
    try:
        total, by = await adapter.stats_facets(group_by=["year", "type"], allowed_levels=None)
    finally:
        await adapter.aclose()
    assert total == 32268
    assert by["year"] == {"2023": 100, "2022": 90}
    assert "type" not in by  # facet type không khả dụng -> bỏ qua


@respx.mock
async def test_stats_facets_partner_public_only_calls_discovery_anonymously():
    # client CÓ service account -> mặc định đính Bearer; nhưng partner (public-only) phải
    # gọi Discovery ẩn danh để DSpace tự lọc theo quyền đọc Anonymous.
    respx.get(f"{BASE}/security/csrf").mock(
        return_value=httpx.Response(204, headers={"DSPACE-XSRF-TOKEN": "c"})
    )
    respx.post(f"{BASE}/authn/login").mock(
        return_value=httpx.Response(200, headers={"Authorization": "Bearer jwt"})
    )
    search = respx.get(f"{BASE}/discover/search/objects").mock(
        return_value=httpx.Response(200, json=_search_objects([], total=5))
    )
    settings = _settings()
    client = DSpace7Client(
        base_url=BASE, service_email="svc@hpu.edu.vn", service_password="s"
    )
    adapter = DSpace7Adapter(client=client, settings=settings)
    try:
        total, _ = await adapter.stats_facets(group_by=[], allowed_levels=("public",))
    finally:
        await adapter.aclose()
    assert total == 5
    assert "Authorization" not in search.calls.last.request.headers


# --- health ---


@respx.mock
async def test_health_ok_and_down():
    respx.get(f"{BASE}/authn/status").mock(return_value=httpx.Response(200, json={"authenticated": False}))
    adapter = _make_adapter()
    try:
        assert (await adapter.health()).status == "ok"
    finally:
        await adapter.aclose()

    with respx.mock:
        respx.get(f"{BASE}/authn/status").mock(return_value=httpx.Response(503))
        adapter2 = _make_adapter()
        try:
            assert (await adapter2.health()).status == "down"
        finally:
            await adapter2.aclose()


# --- tích hợp qua DSpaceProvider: enforce quyền chạy đúng trên adapter v7 ---


@respx.mock
async def test_provider_search_through_v7_enforces_partner_sees_only_public():
    items = [_hal_item("u1", "1/pub", "Công khai"), _hal_item("u2", "1/res", "Hạn chế")]
    respx.get(f"{BASE}/discover/search/objects").mock(
        return_value=httpx.Response(200, json=_search_objects(items, total=2))
    )
    # provider.get() gọi lại từng item + accessStatus
    respx.get(f"{BASE}/core/items/u1").mock(return_value=httpx.Response(200, json=_hal_item("u1", "1/pub", "Công khai")))
    respx.get(f"{BASE}/core/items/u1/accessStatus").mock(
        return_value=httpx.Response(200, json={"status": "open.access"})
    )
    respx.get(f"{BASE}/core/items/u2").mock(return_value=httpx.Response(200, json=_hal_item("u2", "1/res", "Hạn chế")))
    respx.get(f"{BASE}/core/items/u2/accessStatus").mock(
        return_value=httpx.Response(200, json={"status": "restricted"})
    )

    settings = _settings()
    adapter = DSpace7Adapter(client=DSpace7Client(base_url=BASE), settings=settings)
    provider = DSpaceProvider(settings=settings, adapter=adapter)
    try:
        result = await provider.search("x", allowed_levels=("public",))
    finally:
        await provider.aclose()
    # partner chỉ thấy item public; item restricted bị ẩn khỏi kết quả (không lỗi cả trang)
    assert [r.title for r in result.results] == ["Công khai"]
    assert result.total == 2  # numFound thô (chưa trừ item bị lọc) — nhất quán 6.x
