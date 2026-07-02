"""Pipeline đồng bộ Tầng 3 (embedding) — 02-architecture.md §6.

CHƯA chạy được thật từ máy dev này (không có Postgres/GEMINI_API_KEY/LAN DSpace) — cấu
trúc theo đúng sequence diagram trong tài liệu, có unit test bằng fake (không cần hạ
tầng thật). Chạy: `python -m hpu_library_mcp.ingest` sau khi điền `.env` đầy đủ, hoặc qua
script cài đặt `hpu-library-mcp-sync` (xem pyproject.toml).

GIỚI HẠN ĐÃ BIẾT (xem docs/DECISIONS.md Sprint 3):
- DSpace REST 6.x không có filter "đổi từ ngày X" đáng tin cậy -> mỗi lượt quét lại
  `batch_limit` item gần nhất thay vì thật sự "tăng dần". Idempotent (ON CONFLICT ở
  VectorStore.upsert_chunks) nên chạy lại an toàn, chỉ tốn thêm chi phí embedding trùng.
- Chỉ embed được item có bitstream PDF (Tầng 2 hiện chỉ hỗ trợ PDF — xem text/extraction.py).
- Không tự gỡ chunk của item đã bị ẩn/xóa (cần so sánh 2 chiều với DSpace, để dành khi có
  hạ tầng thật để đo chi phí/hành vi chính xác).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

from hpu_library_mcp.config import Settings, get_settings
from hpu_library_mcp.db import Database
from hpu_library_mcp.logging_setup import configure_logging, get_logger
from hpu_library_mcp.providers.dspace.client import DSpaceRestClient
from hpu_library_mcp.providers.dspace.mapping import infer_access_level, map_item_to_resource
from hpu_library_mcp.text.extraction import extract_pages
from hpu_library_mcp.vector.chunker import split_text
from hpu_library_mcp.vector.embedding import EmbeddingProvider
from hpu_library_mcp.vector.gemini_embedding import GeminiEmbeddingProvider
from hpu_library_mcp.vector.store import ChunkRecord, VectorStore

logger = get_logger(__name__)

_SOURCE = "dspace"


@dataclass
class SyncStats:
    items_scanned: int = 0
    items_embedded: int = 0
    items_skipped_no_text: int = 0
    chunks_upserted: int = 0
    embedding_texts_sent: int = 0  # ước lượng chi phí embedding — NFR-8


async def sync_source(
    *,
    settings: Settings,
    rest_client: DSpaceRestClient,
    embedding_provider: EmbeddingProvider,
    vector_store: VectorStore,
    batch_limit: int = 200,
) -> SyncStats:
    """Đồng bộ 1 lượt: lấy item -> bóc text (Tầng 2) -> chunk -> embed theo lô -> upsert."""
    stats = SyncStats()

    raw_items = (
        await rest_client.get_json("/items", params={"limit": batch_limit, "expand": "metadata,bitstreams"}) or []
    )
    stats.items_scanned = len(raw_items)

    for raw_item in raw_items:
        item_uuid = raw_item.get("uuid")
        try:
            policies = await rest_client.get_json(f"/items/{item_uuid}/policy")
        except Exception:
            policies = None  # thiếu policy -> infer_access_level trả restricted (fail-safe)
        access_level = infer_access_level(policies)

        resource = map_item_to_resource(
            raw_item,
            rest_base_url=settings.dspace_rest_base_url,
            public_base_url=settings.dspace_public_base_url,
            resource_policies=policies,
        )
        pdf_files = [f for f in resource.files if f.mime == "application/pdf"]
        if not pdf_files:
            stats.items_skipped_no_text += 1
            continue

        try:
            content = await rest_client.get_bytes(pdf_files[0].bitstream_link)
            pages, _truncated = await asyncio.to_thread(
                extract_pages, content, mime="application/pdf", max_pages=settings.text_extract_max_pages
            )
        except Exception:
            logger.warning("ingest_extract_failed item_id=%s", resource.id)
            stats.items_skipped_no_text += 1
            continue

        full_text = "\n".join(pages)
        chunks_text = split_text(full_text, size=settings.chunk_size_chars, overlap=settings.chunk_overlap_chars)
        if not chunks_text:
            stats.items_skipped_no_text += 1
            continue

        embeddings = await embedding_provider.embed(chunks_text, task_type="document")
        stats.embedding_texts_sent += len(chunks_text)

        records = [
            ChunkRecord(
                source=_SOURCE,
                item_id=resource.id,
                chunk_index=idx,
                content=text,
                embedding=embedding,
                access_level=access_level,
                title=resource.title,
                url=resource.url,
            )
            for idx, (text, embedding) in enumerate(zip(chunks_text, embeddings))
        ]
        await vector_store.upsert_chunks(records)
        stats.chunks_upserted += len(records)
        stats.items_embedded += 1

    await vector_store.set_sync_state(
        source=_SOURCE,
        last_synced_at=datetime.now(timezone.utc),
        last_item_ts=None,
        notes=f"scanned={stats.items_scanned} embedded={stats.items_embedded}",
    )
    logger.info(
        "ingest_sync_done scanned=%s embedded=%s skipped=%s chunks=%s",
        stats.items_scanned,
        stats.items_embedded,
        stats.items_skipped_no_text,
        stats.chunks_upserted,
    )
    return stats


async def _run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    if not settings.gemini_api_key.get_secret_value() or not settings.database_url:
        raise SystemExit("Cần GEMINI_API_KEY và DATABASE_URL trong .env trước khi chạy đồng bộ.")

    rest_client = DSpaceRestClient(
        base_url=settings.dspace_rest_base_url,
        timeout=settings.dspace_http_timeout_seconds,
        service_email=settings.dspace_service_email,
        service_password=settings.dspace_service_password.get_secret_value(),
    )
    embedding_provider = GeminiEmbeddingProvider(
        api_key=settings.gemini_api_key.get_secret_value(),
        model=settings.gemini_embedding_model,
        dimensions=settings.gemini_embedding_dimensions,
        batch_size=settings.gemini_embedding_batch_size,
        timeout=settings.gemini_http_timeout_seconds,
    )
    database = Database(settings.database_url)
    await database.ensure_schema(embedding_dimensions=settings.gemini_embedding_dimensions)
    vector_store = VectorStore(database)

    try:
        stats = await sync_source(
            settings=settings,
            rest_client=rest_client,
            embedding_provider=embedding_provider,
            vector_store=vector_store,
        )
    finally:
        await rest_client.aclose()
        await embedding_provider.aclose()
        await database.aclose()

    logger.info("ingest_done %s", stats)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
