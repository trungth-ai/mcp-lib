"""Bộ test bảo mật đầy đủ theo 06-test-plan.md §2.4 — ĐIỀU KIỆN CHẶN MERGE.

Test ở tầng server.py (gọi thẳng hàm tool đã đăng ký `@mcp.tool()`), đi qua đúng luồng
thật: FakeContext (giả lập header HTTP) -> resolve_identity -> allowed_levels -> provider.
Không dựng FastMCP Context thật (phụ thuộc nội bộ SDK) — chỉ cần đúng hình dạng
`ctx.request_context.request.headers` mà security/resolve.py thực sự đọc (đã xác nhận ở
tests/test_resolve_identity.py).
"""

from __future__ import annotations

import json

import pytest

import hpu_library_mcp.server as server
from hpu_library_mcp.config import Settings
from hpu_library_mcp.providers.dspace.provider import DSpaceProvider
from hpu_library_mcp.providers.registry import ProviderRegistry
from hpu_library_mcp.security.keys import ApiKeyRecord
from tests.conftest import (
    ANON_READ_POLICY,
    INTERNAL_READ_POLICY,
    FakeDSpaceRestClient,
    FakeEmbeddingProvider,
    FakeSolrClient,
    FakeVectorStore,
    http_ctx,
)

PARTNER_TOKEN = "partner-token"  # noqa: S105 - key giả lập cho test, không phải secret thật
INTERNAL_TOKEN = "internal-token"  # noqa: S105

PUBLIC_HANDLE = "123456789/42"
RESTRICTED_HANDLE = "123456789/99"


class FakeMultiKeyStore:
    def __init__(self, keys: dict[str, ApiKeyRecord]) -> None:
        self._keys = keys

    async def resolve(self, raw_key: str) -> ApiKeyRecord | None:
        return self._keys.get(raw_key)


def _restricted_item(sample_item: dict) -> dict:
    item = dict(sample_item)
    item["uuid"] = "item-uuid-restricted"
    item["handle"] = RESTRICTED_HANDLE
    item["metadata"] = [{"key": "dc.title", "value": "Tài liệu nội bộ"}]
    # bitstream riêng (uuid khác) — không dùng chung "bit-1" với item public, tránh
    # policy của 2 bitstream khác nhau bị lẫn vào nhau trong dữ liệu test.
    item["bitstreams"] = [
        {
            "uuid": "bit-restricted",
            "name": "noibo.pdf",
            "bundleName": "ORIGINAL",
            "mimeType": "application/pdf",
            "sizeBytes": 1000,
            "retrieveLink": "/bitstreams/bit-restricted/retrieve",
        }
    ]
    return item


@pytest.fixture
def wired_server(monkeypatch, sample_item):
    """Cắm provider (route giả) + key store (partner/internal) vào server.py, gọi tool thật."""
    restricted_item = _restricted_item(sample_item)

    rest_routes = {
        f"/handle/{PUBLIC_HANDLE}": sample_item,
        "/items/item-uuid-1/policy": ANON_READ_POLICY,
        f"/handle/{RESTRICTED_HANDLE}": restricted_item,
        "/items/item-uuid-restricted/policy": INTERNAL_READ_POLICY,
        "/items": [sample_item, restricted_item],
        "/bitstreams/bit-1/policy": ANON_READ_POLICY,
        "/bitstreams/bit-restricted/policy": INTERNAL_READ_POLICY,
    }
    # 1 response thỏa cả 2 parser (search_library đọc response.docs, library_stats đọc
    # response.numFound + facet_counts) — mỗi test trong file này chỉ gọi 1 trong 2 tool
    # nên không cần mô phỏng thứ tự nhiều lần gọi khác nhau.
    combined_solr_response = {
        "response": {"numFound": 2, "docs": [{"handle": PUBLIC_HANDLE}, {"handle": RESTRICTED_HANDLE}]},
        "facet_counts": {"facet_fields": {}},
    }

    rest_client = FakeDSpaceRestClient(rest_routes)
    solr_client = FakeSolrClient(combined_solr_response)
    embedding_provider = FakeEmbeddingProvider()
    vector_store = FakeVectorStore(chunks=[])

    provider = DSpaceProvider(
        settings=Settings(),
        client=rest_client,
        solr_client=solr_client,
        embedding_provider=embedding_provider,
        vector_store=vector_store,
    )
    registry = ProviderRegistry()
    registry.register(provider)

    key_store = FakeMultiKeyStore(
        {
            PARTNER_TOKEN: ApiKeyRecord(id="partner-1", scope="partner", rate_limit=1000),
            INTERNAL_TOKEN: ApiKeyRecord(id="internal-1", scope="internal", rate_limit=1000),
        }
    )

    monkeypatch.setattr(server, "_registry", registry)
    monkeypatch.setattr(server, "_key_store", key_store)
    monkeypatch.setattr(server, "_key_store_resolved", True)
    return {"vector_store": vector_store, "solr_client": solr_client}


def partner_ctx():
    return http_ctx(bearer_token=PARTNER_TOKEN)


def internal_ctx():
    return http_ctx(bearer_token=INTERNAL_TOKEN)


# --- get_item ---


async def test_get_item_partner_sees_public(wired_server):
    result = await server.get_item(id=PUBLIC_HANDLE, ctx=partner_ctx())
    assert "error" not in result
    assert result["access_level"] == "public"


async def test_get_item_partner_forbidden_on_restricted(wired_server):
    result = await server.get_item(id=RESTRICTED_HANDLE, ctx=partner_ctx())
    assert result["error"]["code"] == "FORBIDDEN"


async def test_get_item_internal_sees_restricted(wired_server):
    result = await server.get_item(id=RESTRICTED_HANDLE, ctx=internal_ctx())
    assert "error" not in result
    assert result["access_level"] == "internal"


# --- get_bitstream_link ---


async def test_get_bitstream_link_partner_forbidden_on_restricted(wired_server):
    result = await server.get_bitstream_link(
        item_id=RESTRICTED_HANDLE, bitstream_id="bit-restricted", ctx=partner_ctx()
    )
    assert result["error"]["code"] == "FORBIDDEN"


async def test_get_bitstream_link_internal_allowed_on_restricted(wired_server):
    result = await server.get_bitstream_link(
        item_id=RESTRICTED_HANDLE, bitstream_id="bit-restricted", ctx=internal_ctx()
    )
    assert "error" not in result


# --- search_library ---


async def test_search_library_partner_excludes_restricted_item(wired_server):
    result = await server.search_library(query="tuyển sinh", ctx=partner_ctx())
    ids = [r["id"] for r in result["results"]]
    assert PUBLIC_HANDLE in ids
    assert RESTRICTED_HANDLE not in ids


async def test_search_library_internal_sees_both(wired_server):
    result = await server.search_library(query="tuyển sinh", ctx=internal_ctx())
    ids = [r["id"] for r in result["results"]]
    assert PUBLIC_HANDLE in ids
    assert RESTRICTED_HANDLE in ids


# --- get_recent_items ---


async def test_get_recent_items_partner_excludes_restricted_item(wired_server):
    result = await server.get_recent_items(ctx=partner_ctx())
    ids = [item["id"] for item in result["items"]]
    assert RESTRICTED_HANDLE not in ids


async def test_get_recent_items_internal_sees_restricted_item(wired_server):
    result = await server.get_recent_items(ctx=internal_ctx())
    ids = [item["id"] for item in result["items"]]
    assert RESTRICTED_HANDLE in ids


# --- library_stats: partner bị lọc ở Solr qua field `read` ---


async def test_library_stats_partner_adds_read_filter(wired_server):
    await server.library_stats(ctx=partner_ctx())
    solr_client = wired_server["solr_client"]
    last_params = solr_client.calls[-1]
    assert any(v == "read:g0" for k, v in last_params if k == "fq")


async def test_library_stats_internal_no_read_filter(wired_server):
    await server.library_stats(ctx=internal_ctx())
    solr_client = wired_server["solr_client"]
    last_params = solr_client.calls[-1]
    assert not any(v == "read:g0" for k, v in last_params if k == "fq")


# --- semantic_search_documents: allowed_levels đúng theo scope ---


async def test_semantic_search_partner_restricts_to_public(wired_server):
    await server.semantic_search_documents(query="tuyển sinh", ctx=partner_ctx())
    vector_store = wired_server["vector_store"]
    assert vector_store.search_calls[-1]["allowed_levels"] == ("public",)


async def test_semantic_search_internal_sees_all_levels(wired_server):
    await server.semantic_search_documents(query="tuyển sinh", ctx=internal_ctx())
    vector_store = wired_server["vector_store"]
    assert set(vector_store.search_calls[-1]["allowed_levels"]) == {"public", "internal", "restricted"}


# --- get_document_text / find_in_document ---


async def test_get_document_text_partner_forbidden_on_restricted(wired_server):
    result = await server.get_document_text(id=RESTRICTED_HANDLE, ctx=partner_ctx())
    assert result["error"]["code"] == "FORBIDDEN"


async def test_find_in_document_partner_forbidden_on_restricted(wired_server):
    result = await server.find_in_document(id=RESTRICTED_HANDLE, query="x", ctx=partner_ctx())
    assert result["error"]["code"] == "FORBIDDEN"


# --- Không có key -> luôn bị chặn qua streamable-http (không có ngoại lệ) ---


async def test_no_key_over_http_always_forbidden(wired_server):
    result = await server.get_item(id=PUBLIC_HANDLE, ctx=http_ctx())
    assert result["error"]["code"] == "FORBIDDEN"


# --- Test rò rỉ: log/lỗi không chứa token/API key ---


async def test_forbidden_error_response_never_contains_the_raw_token(wired_server):
    result = await server.get_item(id=PUBLIC_HANDLE, ctx=http_ctx(bearer_token="token-khong-hop-le-12345"))
    dumped = json.dumps(result, ensure_ascii=False)
    assert "token-khong-hop-le-12345" not in dumped
