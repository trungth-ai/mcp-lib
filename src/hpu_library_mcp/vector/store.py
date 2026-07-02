"""VectorStore — bọc asyncpg cho pgvector Tầng 3 (04-data-model.md §2)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from hpu_library_mcp.db import Database
from hpu_library_mcp.errors import UpstreamError
from hpu_library_mcp.logging_setup import get_logger
from hpu_library_mcp.models import AccessLevel, Chunk
from hpu_library_mcp.vector import queries

logger = get_logger(__name__)


class ChunkRecord:
    """1 chunk sẵn sàng upsert. `access_level` gán NGAY LÚC INGEST (đóng băng theo policy
    tại thời điểm đó; đồng bộ lại khi policy đổi — xem 05-security.md §4)."""

    def __init__(
        self,
        *,
        source: str,
        item_id: str,
        chunk_index: int,
        content: str,
        embedding: list[float],
        access_level: AccessLevel,
        page: int | None = None,
        title: str | None = None,
        url: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        self.source = source
        self.item_id = item_id
        self.chunk_index = chunk_index
        self.content = content
        self.embedding = embedding
        self.access_level = access_level
        self.page = page
        self.title = title
        self.url = url
        self.meta = meta


class VectorStore:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def upsert_chunks(self, chunks: list[ChunkRecord]) -> None:
        """Idempotent theo (source, item_id, chunk_index) — chạy lại không nhân đôi chunk."""
        if not chunks:
            return
        try:
            pool = await self._db.get_pool()
            async with pool.acquire() as conn, conn.transaction():
                for chunk in chunks:
                    await conn.execute(
                        queries.UPSERT_CHUNK_SQL,
                        chunk.source,
                        chunk.item_id,
                        chunk.chunk_index,
                        chunk.content,
                        queries.embedding_to_pgvector_literal(chunk.embedding),
                        chunk.access_level,
                        chunk.page,
                        chunk.title,
                        chunk.url,
                        json.dumps(chunk.meta) if chunk.meta is not None else None,
                    )
        except Exception as exc:
            logger.warning("vector_upsert_failed")
            raise UpstreamError("Không thể lưu dữ liệu ngữ nghĩa lúc này.") from exc

    async def delete_item_chunks(self, *, source: str, item_id: str) -> None:
        pool = await self._db.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(queries.DELETE_ITEM_CHUNKS_SQL, source, item_id)

    async def semantic_search(
        self, *, embedding: list[float], source: str, allowed_levels: tuple[AccessLevel, ...], k: int
    ) -> list[Chunk]:
        params = queries.build_semantic_search_params(
            embedding=embedding, source=source, allowed_levels=allowed_levels, k=k
        )
        try:
            pool = await self._db.get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(queries.SEMANTIC_SEARCH_SQL, *params)
        except Exception as exc:
            logger.warning("vector_search_failed")
            raise UpstreamError("Không thể tìm kiếm ngữ nghĩa lúc này.") from exc
        return [Chunk(**queries.row_to_chunk_kwargs(row)) for row in rows]

    async def get_sync_state(self, source: str) -> dict[str, Any] | None:
        pool = await self._db.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(queries.GET_SYNC_STATE_SQL, source)
        return dict(row) if row else None

    async def set_sync_state(
        self, *, source: str, last_synced_at: datetime, last_item_ts: datetime | None, notes: str | None = None
    ) -> None:
        pool = await self._db.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(queries.UPSERT_SYNC_STATE_SQL, source, last_synced_at, last_item_ts, notes)
