from __future__ import annotations

from datetime import datetime, timezone

import pytest

from hpu_library_mcp.errors import UpstreamError
from hpu_library_mcp.vector.store import ChunkRecord, VectorStore
from tests.conftest import FakeAsyncpgConn, FakeDatabase


def make_store(**conn_kwargs) -> tuple[VectorStore, FakeAsyncpgConn]:
    conn = FakeAsyncpgConn(**conn_kwargs)
    store = VectorStore(FakeDatabase(conn))
    return store, conn


async def test_upsert_chunks_executes_one_statement_per_chunk():
    store, conn = make_store()
    chunks = [
        ChunkRecord(
            source="dspace",
            item_id="123/1",
            chunk_index=0,
            content="đoạn 1",
            embedding=[0.1, 0.2],
            access_level="public",
        ),
        ChunkRecord(
            source="dspace",
            item_id="123/1",
            chunk_index=1,
            content="đoạn 2",
            embedding=[0.3, 0.4],
            access_level="public",
        ),
    ]
    await store.upsert_chunks(chunks)
    assert len(conn.executed) == 2
    sql, args = conn.executed[0]
    assert "ON CONFLICT" in sql
    assert args[0] == "dspace"
    assert args[1] == "123/1"


async def test_upsert_chunks_empty_list_no_op():
    store, conn = make_store()
    await store.upsert_chunks([])
    assert conn.executed == []


async def test_upsert_chunks_wraps_db_error_as_upstream_error():
    class FailingConn(FakeAsyncpgConn):
        async def execute(self, sql, *args):
            raise RuntimeError("db lỗi")

    store = VectorStore(FakeDatabase(FailingConn()))
    chunk = ChunkRecord(
        source="dspace", item_id="1/1", chunk_index=0, content="x", embedding=[0.1], access_level="public"
    )
    with pytest.raises(UpstreamError):
        await store.upsert_chunks([chunk])


async def test_delete_item_chunks_executes_with_correct_params():
    store, conn = make_store()
    await store.delete_item_chunks(source="dspace", item_id="123/1")
    sql, args = conn.executed[0]
    assert "DELETE FROM doc_chunks" in sql
    assert args == ("dspace", "123/1")


async def test_semantic_search_maps_rows_to_chunks():
    row = {
        "item_id": "123/1",
        "chunk_index": 0,
        "content": "nội dung liên quan",
        "title": "Tiêu đề",
        "url": "https://lib.hpu.edu.vn/handle/123/1",
        "page": 3,
        "access_level": "public",
        "score": 0.9,
    }
    store, conn = make_store(fetch_result=[row])
    chunks = await store.semantic_search(
        embedding=[0.1, 0.2], source="dspace", allowed_levels=("public",), k=5
    )
    assert len(chunks) == 1
    assert chunks[0].item_id == "123/1"
    assert chunks[0].score == pytest.approx(0.9)
    sql, args = conn.executed[0]
    assert "access_level = ANY($3)" in sql
    assert args[2] == ["public"]


async def test_semantic_search_wraps_db_error_as_upstream_error():
    class FailingConn(FakeAsyncpgConn):
        async def fetch(self, sql, *args):
            raise RuntimeError("db lỗi")

    store = VectorStore(FakeDatabase(FailingConn()))
    with pytest.raises(UpstreamError):
        await store.semantic_search(embedding=[0.1], source="dspace", allowed_levels=("public",), k=5)


async def test_get_sync_state_returns_none_when_absent():
    store, _ = make_store(fetchrow_result=None)
    assert await store.get_sync_state("dspace") is None


async def test_get_sync_state_returns_dict_when_present():
    row = {"source": "dspace", "last_synced_at": datetime.now(timezone.utc), "last_item_ts": None, "notes": None}
    store, _ = make_store(fetchrow_result=row)
    result = await store.get_sync_state("dspace")
    assert result["source"] == "dspace"


async def test_set_sync_state_executes_upsert():
    store, conn = make_store()
    now = datetime.now(timezone.utc)
    await store.set_sync_state(source="dspace", last_synced_at=now, last_item_ts=None, notes="ok")
    sql, args = conn.executed[0]
    assert "INSERT INTO sync_state" in sql
    assert args[0] == "dspace"
