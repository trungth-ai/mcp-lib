"""SQL cho pgvector (`doc_chunks`/`sync_state`) — tách khỏi store.py để test được KHÔNG
cần Postgres thật (06-test-plan.md §2.1: "build câu SQL semantic có kèm access_level =
ANY(...)"). SQL bám sát nguyên văn 04-data-model.md §2.
"""

from __future__ import annotations

from typing import Any

from hpu_library_mcp.models import AccessLevel

UPSERT_CHUNK_SQL = """
INSERT INTO doc_chunks
    (source, item_id, chunk_index, content, embedding, access_level, page, title, url, meta, updated_at)
VALUES ($1, $2, $3, $4, $5::vector, $6, $7, $8, $9, $10::jsonb, now())
ON CONFLICT (source, item_id, chunk_index)
DO UPDATE SET
    content = EXCLUDED.content,
    embedding = EXCLUDED.embedding,
    access_level = EXCLUDED.access_level,
    page = EXCLUDED.page,
    title = EXCLUDED.title,
    url = EXCLUDED.url,
    meta = EXCLUDED.meta,
    updated_at = now()
"""

DELETE_ITEM_CHUNKS_SQL = "DELETE FROM doc_chunks WHERE source = $1 AND item_id = $2"

SEMANTIC_SEARCH_SQL = """
SELECT item_id, chunk_index, content, title, url, page, access_level,
       1 - (embedding <=> $1::vector) AS score
FROM doc_chunks
WHERE source = $2
  AND access_level = ANY($3)
ORDER BY embedding <=> $1::vector
LIMIT $4
"""

GET_SYNC_STATE_SQL = "SELECT source, last_synced_at, last_item_ts, notes FROM sync_state WHERE source = $1"

UPSERT_SYNC_STATE_SQL = """
INSERT INTO sync_state (source, last_synced_at, last_item_ts, notes)
VALUES ($1, $2, $3, $4)
ON CONFLICT (source) DO UPDATE SET
    last_synced_at = EXCLUDED.last_synced_at,
    last_item_ts = EXCLUDED.last_item_ts,
    notes = EXCLUDED.notes
"""


def embedding_to_pgvector_literal(embedding: list[float]) -> str:
    """Chuyển vector Python -> literal text pgvector chấp nhận, vd "[0.1,0.2,0.3]"."""
    return "[" + ",".join(str(float(v)) for v in embedding) + "]"


def build_semantic_search_params(
    *, embedding: list[float], source: str, allowed_levels: tuple[AccessLevel, ...], k: int
) -> list[Any]:
    if not allowed_levels:
        raise ValueError("allowed_levels rỗng — sẽ không khớp access_level nào (fail-safe, không phải lỗi ngầm)")
    return [embedding_to_pgvector_literal(embedding), source, list(allowed_levels), max(1, min(k, 100))]


def row_to_chunk_kwargs(row: Any) -> dict[str, Any]:
    """Map 1 record asyncpg (hoặc dict tương đương trong test) -> kwargs dựng models.Chunk."""
    return {
        "item_id": row["item_id"],
        "chunk_index": row["chunk_index"],
        "text": row["content"],
        "score": float(row["score"]),
        "title": row["title"],
        "url": row["url"],
        "page": row["page"],
        "access_level": row["access_level"],
    }
