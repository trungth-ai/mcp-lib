"""Rate limit qua đúng đường server.py thật (06-test-plan.md §2.5: "Kiểm rate limit chặn
đúng ngưỡng theo key") — khác tests/test_rate_limit.py (chỉ test class RateLimiter riêng
lẻ), file này xác nhận `_handle_errors` trong server.py THỰC SỰ gọi RateLimiter và trả
đúng lỗi `RATE_LIMITED` khi vượt ngưỡng của key.
"""

from __future__ import annotations

import hpu_library_mcp.server as server
from hpu_library_mcp.config import Settings
from hpu_library_mcp.providers.dspace.provider import DSpaceProvider
from hpu_library_mcp.providers.registry import ProviderRegistry
from hpu_library_mcp.security.keys import ApiKeyRecord
from hpu_library_mcp.security.rate_limit import RateLimiter
from tests.conftest import ANON_READ_POLICY, FakeDSpaceRestClient, http_ctx, stdio_ctx


class _FakeKeyStore:
    def __init__(self, keys: dict[str, ApiKeyRecord]) -> None:
        self._keys = keys

    async def resolve(self, raw_key: str) -> ApiKeyRecord | None:
        return self._keys.get(raw_key)


def _wire(monkeypatch, sample_item, *, key_store) -> None:
    rest_routes = {
        "/handle/123456789/42": sample_item,
        "/items/item-uuid-1/policy": ANON_READ_POLICY,
    }
    registry = ProviderRegistry()
    registry.register(DSpaceProvider(settings=Settings(), client=FakeDSpaceRestClient(rest_routes)))

    monkeypatch.setattr(server, "_registry", registry)
    monkeypatch.setattr(server, "_key_store", key_store)
    monkeypatch.setattr(server, "_key_store_resolved", True)
    monkeypatch.setattr(server, "_rate_limiter", RateLimiter())  # bộ đếm sạch riêng cho từng test


async def test_key_blocked_after_exceeding_its_rate_limit(monkeypatch, sample_item):
    key_store = _FakeKeyStore({"limited-key": ApiKeyRecord(id="limited-1", scope="internal", rate_limit=2)})
    _wire(monkeypatch, sample_item, key_store=key_store)
    ctx = http_ctx(bearer_token="limited-key")

    r1 = await server.get_item(id="123456789/42", ctx=ctx)
    r2 = await server.get_item(id="123456789/42", ctx=ctx)
    r3 = await server.get_item(id="123456789/42", ctx=ctx)

    assert "error" not in r1
    assert "error" not in r2
    assert r3["error"]["code"] == "RATE_LIMITED"


async def test_different_keys_have_independent_rate_limits(monkeypatch, sample_item):
    key_store = _FakeKeyStore(
        {
            "key-a": ApiKeyRecord(id="a", scope="internal", rate_limit=1),
            "key-b": ApiKeyRecord(id="b", scope="internal", rate_limit=1),
        }
    )
    _wire(monkeypatch, sample_item, key_store=key_store)

    r_a1 = await server.get_item(id="123456789/42", ctx=http_ctx(bearer_token="key-a"))
    r_a2 = await server.get_item(id="123456789/42", ctx=http_ctx(bearer_token="key-a"))
    r_b1 = await server.get_item(id="123456789/42", ctx=http_ctx(bearer_token="key-b"))

    assert "error" not in r_a1
    assert r_a2["error"]["code"] == "RATE_LIMITED"
    assert "error" not in r_b1  # key-b chưa dùng lượt nào, không bị ảnh hưởng bởi key-a


async def test_stdio_local_client_never_rate_limited(monkeypatch, sample_item):
    _wire(monkeypatch, sample_item, key_store=_FakeKeyStore({}))
    for _ in range(20):
        result = await server.get_item(id="123456789/42", ctx=stdio_ctx())
        assert "error" not in result
