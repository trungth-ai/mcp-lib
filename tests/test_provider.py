from __future__ import annotations

import pytest

from hpu_library_mcp.config import Settings
from hpu_library_mcp.errors import ForbiddenError, NotFoundError, UpstreamError
from hpu_library_mcp.providers.dspace.provider import DSpaceProvider
from tests.conftest import ANON_READ_POLICY, INTERNAL_READ_POLICY, FakeDSpaceRestClient


def make_provider(routes: dict) -> tuple[DSpaceProvider, FakeDSpaceRestClient]:
    settings = Settings()
    client = FakeDSpaceRestClient(routes)
    return DSpaceProvider(settings=settings, client=client), client


async def test_get_returns_resource(sample_item):
    provider, _ = make_provider(
        {
            "/handle/123456789/42": sample_item,
            "/items/item-uuid-1/policy": ANON_READ_POLICY,
        }
    )
    resource = await provider.get("123456789/42")
    assert resource.title == "Ứng dụng học máy trong dự báo tuyển sinh"
    assert resource.access_level == "public"


async def test_get_raises_forbidden_when_outside_allowed_levels(sample_item):
    provider, _ = make_provider(
        {
            "/handle/123456789/42": sample_item,
            "/items/item-uuid-1/policy": INTERNAL_READ_POLICY,
        }
    )
    with pytest.raises(ForbiddenError):
        await provider.get("123456789/42", allowed_levels=("public",))


async def test_get_allows_when_within_allowed_levels(sample_item):
    provider, _ = make_provider(
        {
            "/handle/123456789/42": sample_item,
            "/items/item-uuid-1/policy": INTERNAL_READ_POLICY,
        }
    )
    resource = await provider.get("123456789/42", allowed_levels=("public", "internal"))
    assert resource.access_level == "internal"


async def test_get_no_enforcement_when_allowed_levels_is_none(sample_item):
    # Sprint 1 chưa có tầng auth/API key -> allowed_levels=None nghĩa là không lọc.
    provider, _ = make_provider(
        {
            "/handle/123456789/42": sample_item,
            "/items/item-uuid-1/policy": [],  # -> restricted
        }
    )
    resource = await provider.get("123456789/42")
    assert resource.access_level == "restricted"


async def test_get_bitstream_link_not_found_raises(sample_item):
    provider, _ = make_provider(
        {
            "/handle/123456789/42": sample_item,
            "/items/item-uuid-1/policy": ANON_READ_POLICY,
        }
    )
    with pytest.raises(NotFoundError):
        await provider.get_bitstream_link("123456789/42", "khong-ton-tai")


async def test_get_bitstream_link_reports_requires_auth_for_restricted(sample_item):
    provider, _ = make_provider(
        {
            "/handle/123456789/42": sample_item,
            "/items/item-uuid-1/policy": INTERNAL_READ_POLICY,
            "/bitstreams/bit-1/policy": INTERNAL_READ_POLICY,
        }
    )
    link = await provider.get_bitstream_link("123456789/42", "bit-1")
    assert link.requires_auth is True
    assert link.access_level == "internal"


async def test_get_bitstream_link_public_does_not_require_auth(sample_item):
    provider, _ = make_provider(
        {
            "/handle/123456789/42": sample_item,
            "/items/item-uuid-1/policy": ANON_READ_POLICY,
            "/bitstreams/bit-1/policy": ANON_READ_POLICY,
        }
    )
    link = await provider.get_bitstream_link("123456789/42", "bit-1")
    assert link.requires_auth is False
    assert link.access_level == "public"


async def test_get_bitstream_link_enforces_allowed_levels(sample_item):
    provider, _ = make_provider(
        {
            "/handle/123456789/42": sample_item,
            "/items/item-uuid-1/policy": INTERNAL_READ_POLICY,
            "/bitstreams/bit-1/policy": INTERNAL_READ_POLICY,
        }
    )
    with pytest.raises(ForbiddenError):
        await provider.get_bitstream_link("123456789/42", "bit-1", allowed_levels=("public",))


async def test_get_recent_items_sorts_by_accessioned_desc_and_respects_limit(sample_item):
    def make_item(uuid: str, handle: str, title: str, accessioned: str) -> dict:
        item = dict(sample_item)
        item["uuid"] = uuid
        item["handle"] = handle
        item["metadata"] = [
            {"key": "dc.title", "value": title},
            {"key": "dc.date.accessioned", "value": accessioned},
        ]
        return item

    item_a = make_item("a", "1/a", "Cũ hơn", "2023-01-01")
    item_b = make_item("b", "1/b", "Mới nhất", "2024-06-01")
    item_c = make_item("c", "1/c", "Giữa", "2023-12-01")

    provider, client = make_provider(
        {
            "/items": [item_a, item_b, item_c],
            "/items/a/policy": ANON_READ_POLICY,
            "/items/b/policy": ANON_READ_POLICY,
            "/items/c/policy": ANON_READ_POLICY,
        }
    )
    items = await provider.get_recent_items(limit=2)
    assert [r.title for r in items] == ["Mới nhất", "Giữa"]


async def test_get_recent_items_filters_by_allowed_levels(sample_item):
    def make_item(uuid: str, handle: str, title: str) -> dict:
        item = dict(sample_item)
        item["uuid"] = uuid
        item["handle"] = handle
        item["metadata"] = [{"key": "dc.title", "value": title}]
        return item

    item_public = make_item("pub", "1/pub", "Công khai")
    item_restricted = make_item("res", "1/res", "Hạn chế")

    provider, _ = make_provider(
        {
            "/items": [item_public, item_restricted],
            "/items/pub/policy": ANON_READ_POLICY,
            "/items/res/policy": [],
        }
    )
    items = await provider.get_recent_items(limit=10, allowed_levels=("public",))
    assert [r.title for r in items] == ["Công khai"]


async def test_health_ok():
    provider, _ = make_provider({"/status": {"okay": True}})
    health = await provider.health()
    assert health.status == "ok"


async def test_health_down_when_upstream_fails():
    provider, _ = make_provider({"/status": UpstreamError()})
    health = await provider.health()
    assert health.status == "down"
