from __future__ import annotations

from hpu_library_mcp.providers.dspace.solr_search import (
    build_search_params,
    escape_solr_value,
    parse_facet_stats_response,
    parse_search_response,
    strip_highlighting_params,
)

FIELDS = dict(
    default_field="default",
    fulltext_field="fulltext",
    handle_field="handle",
    resourcetype_field="search.resourcetype",
    resourcetype_item_value="2",
    collection_field="location.coll",
    community_field="location.comm",
    year_field="dc.date.issued_year",
    type_field="dc.type_filter",
    author_field="dc.contributor.author_filter",
)


def _param_dict_multi(params: list[tuple[str, object]]) -> dict[str, list[object]]:
    out: dict[str, list[object]] = {}
    for k, v in params:
        out.setdefault(k, []).append(v)
    return out


def test_escape_solr_value_escapes_special_chars_not_vietnamese():
    escaped = escape_solr_value('tuyển sinh: (2023)')
    assert "tuyển sinh" in escaped  # tiếng Việt giữ nguyên
    assert "\\:" in escaped
    assert "\\(" in escaped and "\\)" in escaped


def test_build_search_params_metadata_scope_no_highlight():
    params = build_search_params(
        query="tuyển sinh", scope="metadata", filters=None, facets=None, page=1, page_size=10, **FIELDS
    )
    d = _param_dict_multi(params)
    assert d["df"] == ["default"]
    assert "hl" not in d
    assert d["start"] == [0]
    assert d["rows"] == [10]


def test_build_search_params_fulltext_scope_enables_highlight_and_df():
    params = build_search_params(
        query="tuyển sinh", scope="fulltext", filters=None, facets=None, page=2, page_size=10, **FIELDS
    )
    d = _param_dict_multi(params)
    assert d["df"] == ["fulltext"]
    assert d["hl"] == ["true"]
    assert d["hl.fl"] == ["fulltext"]
    assert d["start"] == [10]  # page 2 -> offset 10


def test_build_search_params_applies_filters_as_fq():
    params = build_search_params(
        query="học máy",
        scope="metadata",
        filters={"collection": "123/1", "type": "Thesis", "author": "Nguyễn Văn A", "year_from": 2020, "year_to": 2024},
        facets=None,
        page=1,
        page_size=10,
        **FIELDS,
    )
    d = _param_dict_multi(params)
    fq_values = d["fq"]
    # "/" bị escape (\/) vì là ký tự đặc biệt Lucene — so sánh qua escape_solr_value thay vì hardcode.
    assert any(f'location.coll:"{escape_solr_value("123/1")}"' in fq for fq in fq_values)
    assert any('dc.type_filter:"Thesis"' in fq for fq in fq_values)
    assert any("Nguyễn" in fq for fq in fq_values)
    assert any("dc.date.issued_year:[2020 TO 2024]" in fq for fq in fq_values)


def test_build_search_params_requests_facets():
    params = build_search_params(
        query="x", scope="metadata", filters=None, facets=["type", "year", "unknown"], page=1, page_size=10, **FIELDS
    )
    d = _param_dict_multi(params)
    assert d["facet"] == ["true"]
    assert "dc.type_filter" in d["facet.field"]
    assert "dc.date.issued_year" in d["facet.field"]
    assert len(d["facet.field"]) == 2  # "unknown" bị bỏ qua


def test_strip_highlighting_params_removes_hl_keys():
    params = build_search_params(
        query="x", scope="fulltext", filters=None, facets=None, page=1, page_size=10, **FIELDS
    )
    stripped = strip_highlighting_params(params)
    assert not any(str(k).startswith("hl") for k, _ in stripped)
    assert any(k == "df" for k, _ in stripped)


def test_parse_search_response_pairs_highlights_by_position():
    raw = {
        "response": {"numFound": 2, "docs": [{"handle": "1/a"}, {"handle": "1/b"}]},
        "highlighting": {
            "doc-a": {"fulltext": ["đoạn <em>khớp</em> A"]},
            "doc-b": {"fulltext": ["đoạn <em>khớp</em> B"]},
        },
    }
    total, results, facets = parse_search_response(raw, handle_field="handle")
    assert total == 2
    assert results[0] == ("1/a", ["đoạn <em>khớp</em> A"])
    assert results[1] == ("1/b", ["đoạn <em>khớp</em> B"])


def test_parse_search_response_skips_docs_missing_handle_field():
    raw = {"response": {"numFound": 1, "docs": [{"other_field": "x"}]}}
    total, results, _ = parse_search_response(raw, handle_field="handle")
    assert total == 1
    assert results == []


def test_parse_search_response_no_highlighting_section_returns_empty_snippets():
    raw = {"response": {"numFound": 1, "docs": [{"handle": "1/a"}]}}
    _, results, _ = parse_search_response(raw, handle_field="handle")
    assert results == [("1/a", [])]


def test_parse_search_response_mismatched_highlight_count_degrades_to_no_highlight():
    # 2 docs nhưng chỉ có 1 highlighting entry -> không đáng tin, bỏ qua toàn bộ (an toàn).
    raw = {
        "response": {"numFound": 2, "docs": [{"handle": "1/a"}, {"handle": "1/b"}]},
        "highlighting": {"only-one": {"fulltext": ["..."]}},
    }
    _, results, _ = parse_search_response(raw, handle_field="handle")
    assert results == [("1/a", []), ("1/b", [])]


def test_parse_search_response_facets():
    raw = {
        "response": {"numFound": 0, "docs": []},
        "facet_counts": {"facet_fields": {"dc.type_filter": ["Thesis", 40, "Article", 12]}},
    }
    _, _, facets = parse_search_response(raw, handle_field="handle")
    assert facets == {"dc.type_filter": {"Thesis": 40, "Article": 12}}


def test_parse_facet_stats_response():
    raw = {
        "response": {"numFound": 500},
        "facet_counts": {"facet_fields": {"dc.type_filter": ["Thesis", 300, "Article", 200]}},
    }
    total, facets = parse_facet_stats_response(raw)
    assert total == 500
    assert facets["dc.type_filter"]["Thesis"] == 300
