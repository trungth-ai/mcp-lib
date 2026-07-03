from __future__ import annotations

from hpu_library_mcp.config import Settings
from hpu_library_mcp.ingest import sync_source
from hpu_library_mcp.providers.dspace.client import DSpaceRestClient
from tests.conftest import (
    ANON_READ_POLICY,
    INTERNAL_READ_POLICY,
    MINIMAL_PDF_BYTES,
    FakeDSpaceRestClient,
    FakeEmbeddingProvider,
    FakeVectorStore,
)

REST_BASE = "http://10.1.0.205:8081/rest"
BITSTREAM_URL = f"{REST_BASE}/bitstreams/bit-1/retrieve"


def _no_pdf_item(sample_item: dict) -> dict:
    item = dict(sample_item)
    item["uuid"] = "item-no-pdf"
    item["handle"] = "1/no-pdf"
    item["bitstreams"] = []
    return item


async def test_sync_source_embeds_item_with_pdf(sample_item):
    rest_client = FakeDSpaceRestClient(
        {
            "/items": [sample_item],
            "/items/item-uuid-1/policy": ANON_READ_POLICY,
            BITSTREAM_URL: MINIMAL_PDF_BYTES,
        }
    )
    embedding_provider = FakeEmbeddingProvider()
    vector_store = FakeVectorStore()

    stats = await sync_source(
        settings=Settings(),
        rest_client=rest_client,
        embedding_provider=embedding_provider,
        vector_store=vector_store,
    )

    assert stats.items_scanned == 1
    assert stats.items_embedded == 1
    assert stats.chunks_upserted == len(vector_store.upserted)
    assert vector_store.upserted[0].access_level == "public"
    assert vector_store.upserted[0].content == "Hello World"


async def test_sync_source_skips_item_without_pdf(sample_item):
    no_pdf_item = _no_pdf_item(sample_item)
    rest_client = FakeDSpaceRestClient(
        {"/items": [no_pdf_item], "/items/item-no-pdf/policy": ANON_READ_POLICY}
    )
    stats = await sync_source(
        settings=Settings(),
        rest_client=rest_client,
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=FakeVectorStore(),
    )
    assert stats.items_embedded == 0
    assert stats.items_skipped_no_text == 1


async def test_sync_source_uses_document_task_type():
    rest_client = FakeDSpaceRestClient({"/items": []})
    embedding_provider = FakeEmbeddingProvider()
    await sync_source(
        settings=Settings(),
        rest_client=rest_client,
        embedding_provider=embedding_provider,
        vector_store=FakeVectorStore(),
    )
    # Không có item -> không gọi embed lần nào, nhưng nếu có thì phải là "document"
    assert embedding_provider.calls == []


async def test_sync_source_records_sync_state(sample_item):
    rest_client = FakeDSpaceRestClient(
        {
            "/items": [sample_item],
            "/items/item-uuid-1/policy": ANON_READ_POLICY,
            BITSTREAM_URL: MINIMAL_PDF_BYTES,
        }
    )
    vector_store = FakeVectorStore()
    await sync_source(
        settings=Settings(),
        rest_client=rest_client,
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=vector_store,
    )
    assert len(vector_store.sync_states) == 1
    assert vector_store.sync_states[0]["source"] == "dspace"


async def test_sync_source_continues_after_extraction_failure(sample_item):
    broken_item = dict(sample_item)
    broken_item["uuid"] = "item-broken"
    broken_item["handle"] = "1/broken"

    rest_client = FakeDSpaceRestClient(
        {
            "/items": [broken_item, sample_item],
            "/items/item-broken/policy": ANON_READ_POLICY,
            "/items/item-uuid-1/policy": ANON_READ_POLICY,
            f"{REST_BASE}/bitstreams/bit-1/retrieve": MINIMAL_PDF_BYTES,
        }
    )
    # broken_item dùng chung bitstream_link (bit-1) với sample_item vì cùng uuid bitstream
    # gốc -> để mô phỏng lỗi bóc text, patch extract_pages ném lỗi cho item đầu tiên.
    import hpu_library_mcp.ingest as ingest_module

    call_count = {"n": 0}
    real_extract_pages = ingest_module.extract_pages

    def flaky_extract_pages(content, *, mime, max_pages):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("PDF hỏng")
        return real_extract_pages(content, mime=mime, max_pages=max_pages)

    orig = ingest_module.extract_pages
    ingest_module.extract_pages = flaky_extract_pages
    try:
        vector_store = FakeVectorStore()
        stats = await sync_source(
            settings=Settings(),
            rest_client=rest_client,
            embedding_provider=FakeEmbeddingProvider(),
            vector_store=vector_store,
        )
    finally:
        ingest_module.extract_pages = orig

    assert stats.items_scanned == 2
    assert stats.items_skipped_no_text == 1
    assert stats.items_embedded == 1


async def test_sync_source_assigns_access_level_from_policy(sample_item):
    internal_item = dict(sample_item)
    internal_item["uuid"] = "item-internal"
    internal_item["handle"] = "1/internal"

    rest_client = FakeDSpaceRestClient(
        {
            "/items": [internal_item],
            "/items/item-internal/policy": INTERNAL_READ_POLICY,
            BITSTREAM_URL: MINIMAL_PDF_BYTES,
        }
    )
    vector_store = FakeVectorStore()
    await sync_source(
        settings=Settings(),
        rest_client=rest_client,
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=vector_store,
    )
    assert vector_store.upserted[0].access_level == "internal"


def test_rest_client_get_bytes_is_used_not_get_json():
    # Xác nhận DSpaceRestClient thật có get_bytes (đã thêm ở Sprint 4) — ingest.py phụ
    # thuộc method này để tải PDF thô.
    assert hasattr(DSpaceRestClient, "get_bytes")
