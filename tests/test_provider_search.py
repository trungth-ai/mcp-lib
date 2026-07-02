from __future__ import annotations

import pytest

from hpu_library_mcp.config import Settings
from hpu_library_mcp.errors import SolrBadRequestError
from hpu_library_mcp.providers.dspace.provider import DSpaceProvider
from tests.conftest import (
    ANON_READ_POLICY,
    INTERNAL_READ_POLICY,
    FakeDSpaceRestClient,
    FakeSolrClient,
    solr_params_dict,
)


def make_provider(rest_routes: dict, solr_responses) -> tuple[DSpaceProvider, FakeDSpaceRestClient, FakeSolrClient]:
    settings = Settings()
    rest_client = FakeDSpaceRestClient(rest_routes)
    solr_client = FakeSolrClient(solr_responses)
    provider = DSpaceProvider(settings=settings, client=rest_client, solr_client=solr_client)
    return provider, rest_client, solr_client


def solr_response(*, total: int, handles: list[str]) -> dict:
    return {"response": {"numFound": total, "docs": [{"handle": h} for h in handles]}}


async def test_search_returns_results_with_rest_metadata(sample_item):
    provider, _, solr = make_provider(
        rest_routes={
            "/handle/123456789/42": sample_item,
            "/items/item-uuid-1/policy": ANON_READ_POLICY,
        },
        solr_responses=solr_response(total=1, handles=["123456789/42"]),
    )
    result = await provider.search("tuyển sinh")
    assert result.total == 1
    assert len(result.results) == 1
    assert result.results[0].title == "Ứng dụng học máy trong dự báo tuyển sinh"
    assert result.results[0].access_level == "public"
    assert result.citations[0].id == "123456789/42"


async def test_search_excludes_items_outside_allowed_levels(sample_item):
    internal_item = dict(sample_item)
    internal_item["uuid"] = "item-uuid-2"
    internal_item["handle"] = "123456789/99"

    provider, _, _ = make_provider(
        rest_routes={
            "/handle/123456789/42": sample_item,
            "/items/item-uuid-1/policy": ANON_READ_POLICY,
            "/handle/123456789/99": internal_item,
            "/items/item-uuid-2/policy": INTERNAL_READ_POLICY,
        },
        solr_responses=solr_response(total=2, handles=["123456789/42", "123456789/99"]),
    )
    result = await provider.search("tuyển sinh", allowed_levels=("public",))
    assert [r.id for r in result.results] == ["123456789/42"]
    assert len(result.citations) == 1


async def test_search_degrades_on_bad_request_when_highlight_requested(sample_item):
    provider, _, solr = make_provider(
        rest_routes={
            "/handle/123456789/42": sample_item,
            "/items/item-uuid-1/policy": ANON_READ_POLICY,
        },
        solr_responses=[
            SolrBadRequestError("field full-text sai tên"),
            solr_response(total=1, handles=["123456789/42"]),
        ],
    )
    result = await provider.search("tuyển sinh", scope="fulltext")
    assert result.total == 1
    assert len(solr.calls) == 2
    second_call_params = solr_params_dict(solr.calls[1])
    assert "hl" not in second_call_params  # đã suy biến bỏ highlight


async def test_search_propagates_bad_request_when_not_highlight_related(sample_item):
    provider, _, _ = make_provider(
        rest_routes={},
        solr_responses=SolrBadRequestError("field default sai tên"),
    )
    with pytest.raises(SolrBadRequestError):
        await provider.search("tuyển sinh", scope="metadata")


async def test_search_sends_query_preserving_vietnamese_diacritics():
    provider, _, solr = make_provider(
        rest_routes={},
        solr_responses=solr_response(total=0, handles=[]),
    )
    await provider.search("tuyển sinh đại học")
    sent_params = solr_params_dict(solr.calls[0])
    assert "tuyển sinh đại học" in sent_params["q"][0]


async def test_search_pagination_math():
    provider, _, solr = make_provider(rest_routes={}, solr_responses=solr_response(total=0, handles=[]))
    await provider.search("x", page=3, page_size=20)
    sent_params = solr_params_dict(solr.calls[0])
    assert sent_params["start"] == [40]
    assert sent_params["rows"] == [20]


async def test_stats_returns_totals_and_facets_by_logical_name():
    raw = {
        "response": {"numFound": 128},
        "facet_counts": {
            "facet_fields": {
                "dc.type_filter": ["Thesis", 40, "Article", 20],
                "dc.date.issued_year": ["2023", 12, "2022", 8],
            }
        },
    }
    provider, _, solr = make_provider(rest_routes={}, solr_responses=raw)
    stats = await provider.stats(group_by=["type", "year"])
    assert stats.total_items == 128
    assert stats.by["type"] == {"Thesis": 40, "Article": 20}
    assert stats.by["year"] == {"2023": 12, "2022": 8}
    sent_params = solr_params_dict(solr.calls[0])
    assert sent_params["rows"] == [0]
