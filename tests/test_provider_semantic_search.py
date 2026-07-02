from __future__ import annotations

import pytest

from hpu_library_mcp.config import Settings
from hpu_library_mcp.errors import UpstreamError
from hpu_library_mcp.providers.dspace.provider import DSpaceProvider
from tests.conftest import FakeDSpaceRestClient, FakeEmbeddingProvider, FakeVectorStore


def make_provider(*, embedding_provider=None, vector_store=None) -> DSpaceProvider:
    return DSpaceProvider(
        settings=Settings(),
        client=FakeDSpaceRestClient({}),
        embedding_provider=embedding_provider,
        vector_store=vector_store,
    )


async def test_semantic_search_not_configured_raises_clear_error():
    provider = make_provider()
    with pytest.raises(UpstreamError):
        await provider.semantic_search("tuyển sinh")


async def test_semantic_search_embeds_query_with_query_task_type():
    embedding_provider = FakeEmbeddingProvider(vector=[0.1, 0.2])
    vector_store = FakeVectorStore()
    provider = make_provider(embedding_provider=embedding_provider, vector_store=vector_store)

    await provider.semantic_search("tuyển sinh", k=5)

    assert embedding_provider.calls == [(["tuyển sinh"], "query")]


async def test_semantic_search_defaults_to_all_levels_when_allowed_levels_none():
    embedding_provider = FakeEmbeddingProvider()
    vector_store = FakeVectorStore()
    provider = make_provider(embedding_provider=embedding_provider, vector_store=vector_store)

    await provider.semantic_search("x", allowed_levels=None)

    assert vector_store.search_calls[0]["allowed_levels"] == ("public", "internal", "restricted")


async def test_semantic_search_passes_through_explicit_allowed_levels():
    embedding_provider = FakeEmbeddingProvider()
    vector_store = FakeVectorStore()
    provider = make_provider(embedding_provider=embedding_provider, vector_store=vector_store)

    await provider.semantic_search("x", allowed_levels=("public",))

    assert vector_store.search_calls[0]["allowed_levels"] == ("public",)


async def test_semantic_search_passes_source_and_k():
    embedding_provider = FakeEmbeddingProvider()
    vector_store = FakeVectorStore()
    provider = make_provider(embedding_provider=embedding_provider, vector_store=vector_store)

    await provider.semantic_search("x", k=3)

    call = vector_store.search_calls[0]
    assert call["source"] == "dspace"
    assert call["k"] == 3


async def test_semantic_search_returns_chunks_from_store():
    from hpu_library_mcp.models import Chunk

    chunk = Chunk(item_id="1/1", chunk_index=0, text="nội dung", score=0.9, access_level="public")
    embedding_provider = FakeEmbeddingProvider()
    vector_store = FakeVectorStore(chunks=[chunk])
    provider = make_provider(embedding_provider=embedding_provider, vector_store=vector_store)

    chunks = await provider.semantic_search("x")

    assert chunks == [chunk]
