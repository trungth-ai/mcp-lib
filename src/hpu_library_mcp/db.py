"""Kết nối Postgres dùng chung — pgvector Tầng 3 (`doc_chunks`/`sync_state`, Sprint 3) và
`api_keys` (Sprint 4). 1 container Postgres cho cả 2, khớp 02-architecture.md (khối `PG`).

`ensure_schema()` idempotent (CREATE ... IF NOT EXISTS) — tiện cho dev, KHÔNG thay thế
công cụ migration thật (Alembic) nếu sau này schema phức tạp hơn.
"""

from __future__ import annotations

import asyncpg

from hpu_library_mcp.errors import UpstreamError
from hpu_library_mcp.logging_setup import get_logger

logger = get_logger(__name__)

# vector({dimensions}) cố ý khớp Settings.gemini_embedding_dimensions — xem 04-data-model.md:
# đổi embedding sang số chiều khác thì tạo bảng/cột mới, KHÔNG sửa cột này (phá dữ liệu cũ).
_SCHEMA_SQL_TEMPLATE = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS doc_chunks (
    id            BIGSERIAL PRIMARY KEY,
    source        TEXT        NOT NULL,
    item_id       TEXT        NOT NULL,
    chunk_index   INT         NOT NULL,
    content       TEXT        NOT NULL,
    embedding     vector({dimensions}) NOT NULL,
    access_level  TEXT        NOT NULL DEFAULT 'public',
    page          INT,
    title         TEXT,
    url           TEXT,
    meta          JSONB,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, item_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_doc_chunks_embedding
    ON doc_chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_doc_chunks_access ON doc_chunks (source, access_level);

CREATE TABLE IF NOT EXISTS sync_state (
    source          TEXT PRIMARY KEY,
    last_synced_at  TIMESTAMPTZ,
    last_item_ts    TIMESTAMPTZ,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS api_keys (
    id          TEXT PRIMARY KEY,
    key_hash    TEXT NOT NULL,
    label       TEXT,
    scope       TEXT NOT NULL,
    rate_limit  INT,
    active      BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ DEFAULT now()
);
"""


class Database:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self._pool is not None:
            return
        try:
            self._pool = await asyncpg.create_pool(self._dsn)
        except (OSError, asyncpg.PostgresError) as exc:
            logger.warning("db_connect_failed")
            raise UpstreamError("Không kết nối được cơ sở dữ liệu.") from exc

    async def aclose(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def get_pool(self) -> asyncpg.Pool:
        """Kết nối lười (lazy) — gọi được trực tiếp mà không cần bước khởi động riêng."""
        await self.connect()
        return self.pool

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Database chưa connect() — gọi connect()/get_pool() trước khi dùng.")
        return self._pool

    async def ensure_schema(self, *, embedding_dimensions: int) -> None:
        sql = _SCHEMA_SQL_TEMPLATE.format(dimensions=embedding_dimensions)
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(sql)
