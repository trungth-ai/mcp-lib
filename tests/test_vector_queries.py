from __future__ import annotations

import pytest

from hpu_library_mcp.vector import queries


def test_embedding_to_pgvector_literal_format():
    literal = queries.embedding_to_pgvector_literal([0.1, 0.2, -0.3])
    assert literal == "[0.1,0.2,-0.3]"


def test_embedding_to_pgvector_literal_empty():
    assert queries.embedding_to_pgvector_literal([]) == "[]"


def test_build_semantic_search_params_includes_access_level_filter():
    params = queries.build_semantic_search_params(
        embedding=[0.1, 0.2], source="dspace", allowed_levels=("public",), k=5
    )
    literal, source, allowed, k = params
    assert literal == "[0.1,0.2]"
    assert source == "dspace"
    assert allowed == ["public"]
    assert k == 5


def test_build_semantic_search_params_clamps_k():
    params = queries.build_semantic_search_params(
        embedding=[0.1], source="dspace", allowed_levels=("public",), k=1000
    )
    assert params[3] == 100  # trần hợp lý, tránh k quá lớn


def test_build_semantic_search_params_rejects_empty_allowed_levels():
    with pytest.raises(ValueError):
        queries.build_semantic_search_params(embedding=[0.1], source="dspace", allowed_levels=(), k=5)


def test_semantic_search_sql_filters_by_access_level_any():
    assert "access_level = ANY($3)" in queries.SEMANTIC_SEARCH_SQL
    assert "WHERE source = $2" in queries.SEMANTIC_SEARCH_SQL


def test_upsert_chunk_sql_has_conflict_target_for_idempotency():
    assert "ON CONFLICT (source, item_id, chunk_index)" in queries.UPSERT_CHUNK_SQL


def test_row_to_chunk_kwargs_maps_fields():
    row = {
        "item_id": "123/1",
        "chunk_index": 3,
        "content": "đoạn nội dung",
        "score": "0.87",
        "title": "Tiêu đề",
        "url": "https://lib.hpu.edu.vn/handle/123/1",
        "page": 5,
        "access_level": "public",
    }
    kwargs = queries.row_to_chunk_kwargs(row)
    assert kwargs["text"] == "đoạn nội dung"
    assert kwargs["score"] == pytest.approx(0.87)
    assert kwargs["item_id"] == "123/1"
