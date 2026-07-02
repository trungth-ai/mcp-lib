"""EmbeddingProvider dùng Gemini `gemini-embedding-001` — xem docs/DECISIONS.md Sprint 3
cho nguồn xác minh hình dạng REST API (khác các giả định DSpace/Solr, API Gemini công
khai và đã kiểm tra qua tài liệu chính thức + cookbook của Google trước khi viết).

Endpoint: POST {base_url}/models/{model}:batchEmbedContents
Header:   x-goog-api-key: <key>   (không log — key chỉ nằm trong header client, không
                                    bao giờ đưa vào chuỗi log)
Body:     {"requests": [{"model","content","output_dimensionality","task_type"}, ...]}
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from hpu_library_mcp.errors import EmbeddingError
from hpu_library_mcp.logging_setup import get_logger
from hpu_library_mcp.vector.embedding import EmbeddingProvider, EmbeddingTaskType

logger = get_logger(__name__)

_TASK_TYPE_MAP: dict[EmbeddingTaskType, str] = {"document": "RETRIEVAL_DOCUMENT", "query": "RETRIEVAL_QUERY"}
_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gemini-embedding-001",
        dimensions: int = 1536,
        batch_size: int = 20,
        timeout: float = 30.0,
        base_url: str = _DEFAULT_BASE_URL,
        max_retries: int = 3,
        sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.dimensions = dimensions
        self._model = model
        self._batch_size = max(1, batch_size)
        self._max_retries = max_retries
        self._sleep = sleep_fn
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout, headers={"x-goog-api-key": api_key}
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def embed(self, texts: list[str], *, task_type: EmbeddingTaskType) -> list[list[float]]:
        if not texts:
            return []
        gemini_task_type = _TASK_TYPE_MAP[task_type]
        results: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            results.extend(await self._embed_batch(batch, task_type=gemini_task_type))
        return results

    async def _embed_batch(self, batch: list[str], *, task_type: str) -> list[list[float]]:
        body = {
            "requests": [
                {
                    "model": f"models/{self._model}",
                    "content": {"parts": [{"text": text}]},
                    "output_dimensionality": self.dimensions,
                    "task_type": task_type,
                }
                for text in batch
            ]
        }
        raw = await self._post_with_retry(f"/models/{self._model}:batchEmbedContents", body)
        embeddings = raw.get("embeddings") or []
        if len(embeddings) != len(batch):
            logger.warning("gemini_embedding_count_mismatch expected=%s got=%s", len(batch), len(embeddings))
            raise EmbeddingError()
        return [e.get("values") or [] for e in embeddings]

    async def _post_with_retry(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(self._max_retries):
            try:
                response = await self._http.post(path, json=body)
            except httpx.TimeoutException as exc:
                logger.warning("gemini_embedding_timeout attempt=%s", attempt)
                if attempt == self._max_retries - 1:
                    raise EmbeddingError() from exc
                continue
            except httpx.HTTPError as exc:
                logger.warning("gemini_embedding_network_error attempt=%s", attempt)
                raise EmbeddingError() from exc

            if response.status_code == 429:
                logger.warning("gemini_embedding_rate_limited attempt=%s", attempt)
                if attempt == self._max_retries - 1:
                    raise EmbeddingError("Hệ thống embedding đang quá tải, thử lại sau.")
                await self._sleep(2**attempt)
                continue

            if response.status_code >= 400:
                logger.warning("gemini_embedding_failed status=%s", response.status_code)
                raise EmbeddingError()

            try:
                return response.json()
            except ValueError as exc:
                raise EmbeddingError() from exc

        raise EmbeddingError()
