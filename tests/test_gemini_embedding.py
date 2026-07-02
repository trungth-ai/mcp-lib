from __future__ import annotations

import httpx
import pytest
import respx

from hpu_library_mcp.errors import EmbeddingError
from hpu_library_mcp.vector.gemini_embedding import GeminiEmbeddingProvider

BASE = "https://generativelanguage.googleapis.com/v1beta"


async def _noop_sleep(_seconds: float) -> None:
    return None


def make_provider(**kwargs) -> GeminiEmbeddingProvider:
    return GeminiEmbeddingProvider(
        api_key="test-key", base_url=BASE, sleep_fn=_noop_sleep, batch_size=kwargs.pop("batch_size", 20), **kwargs
    )


@respx.mock
async def test_embed_sends_correct_request_shape_and_header():
    route = respx.post(f"{BASE}/models/gemini-embedding-001:batchEmbedContents").mock(
        return_value=httpx.Response(200, json={"embeddings": [{"values": [0.1, 0.2, 0.3]}]})
    )
    provider = make_provider()
    try:
        result = await provider.embed(["tuyển sinh"], task_type="document")
    finally:
        await provider.aclose()

    assert result == [[0.1, 0.2, 0.3]]
    request = route.calls.last.request
    assert request.headers["x-goog-api-key"] == "test-key"
    import json

    body = json.loads(request.content)
    req = body["requests"][0]
    assert req["model"] == "models/gemini-embedding-001"
    assert req["content"]["parts"][0]["text"] == "tuyển sinh"
    assert req["output_dimensionality"] == 1536
    assert req["task_type"] == "RETRIEVAL_DOCUMENT"


@respx.mock
async def test_embed_query_uses_retrieval_query_task_type():
    route = respx.post(f"{BASE}/models/gemini-embedding-001:batchEmbedContents").mock(
        return_value=httpx.Response(200, json={"embeddings": [{"values": [0.1]}]})
    )
    provider = make_provider()
    try:
        await provider.embed(["câu hỏi"], task_type="query")
    finally:
        await provider.aclose()
    import json

    body = json.loads(route.calls.last.request.content)
    assert body["requests"][0]["task_type"] == "RETRIEVAL_QUERY"


@respx.mock
async def test_embed_empty_list_returns_empty_without_request():
    route = respx.post(f"{BASE}/models/gemini-embedding-001:batchEmbedContents").mock(
        return_value=httpx.Response(200, json={"embeddings": []})
    )
    provider = make_provider()
    try:
        result = await provider.embed([], task_type="document")
    finally:
        await provider.aclose()
    assert result == []
    assert route.call_count == 0


@respx.mock
async def test_embed_batches_requests_by_batch_size():
    route = respx.post(f"{BASE}/models/gemini-embedding-001:batchEmbedContents").mock(
        return_value=httpx.Response(200, json={"embeddings": [{"values": [0.1]}, {"values": [0.2]}]})
    )
    provider = make_provider(batch_size=2)
    texts = ["a", "b", "c", "d"]  # bội số của batch_size để mỗi lô đều trả đủ 2 embedding
    try:
        result = await provider.embed(texts, task_type="document")
    finally:
        await provider.aclose()
    assert len(result) == 4
    assert route.call_count == 2  # 4/2 = 2 lô


@respx.mock
async def test_embed_retries_on_429_then_succeeds():
    route = respx.post(f"{BASE}/models/gemini-embedding-001:batchEmbedContents").mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(200, json={"embeddings": [{"values": [0.1]}]}),
        ]
    )
    provider = make_provider(max_retries=3)
    try:
        result = await provider.embed(["x"], task_type="document")
    finally:
        await provider.aclose()
    assert result == [[0.1]]
    assert route.call_count == 2


@respx.mock
async def test_embed_exhausted_retries_raises_embedding_error():
    respx.post(f"{BASE}/models/gemini-embedding-001:batchEmbedContents").mock(return_value=httpx.Response(429))
    provider = make_provider(max_retries=2)
    try:
        with pytest.raises(EmbeddingError):
            await provider.embed(["x"], task_type="document")
    finally:
        await provider.aclose()


@respx.mock
async def test_embed_4xx_raises_embedding_error_without_leaking_key():
    respx.post(f"{BASE}/models/gemini-embedding-001:batchEmbedContents").mock(return_value=httpx.Response(400))
    provider = make_provider()
    try:
        with pytest.raises(EmbeddingError) as exc_info:
            await provider.embed(["x"], task_type="document")
    finally:
        await provider.aclose()
    assert "test-key" not in str(exc_info.value)


@respx.mock
async def test_embed_count_mismatch_raises_embedding_error():
    respx.post(f"{BASE}/models/gemini-embedding-001:batchEmbedContents").mock(
        return_value=httpx.Response(200, json={"embeddings": [{"values": [0.1]}]})  # thiếu 1 kết quả
    )
    provider = make_provider()
    try:
        with pytest.raises(EmbeddingError):
            await provider.embed(["a", "b"], task_type="document")
    finally:
        await provider.aclose()


@respx.mock
async def test_embed_timeout_raises_embedding_error():
    respx.post(f"{BASE}/models/gemini-embedding-001:batchEmbedContents").mock(
        side_effect=httpx.TimeoutException("timeout")
    )
    provider = make_provider(max_retries=1)
    try:
        with pytest.raises(EmbeddingError):
            await provider.embed(["x"], task_type="document")
    finally:
        await provider.aclose()
