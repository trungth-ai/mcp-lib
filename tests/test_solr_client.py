from __future__ import annotations

import httpx
import pytest
import respx

from hpu_library_mcp.errors import SolrBadRequestError, UpstreamError
from hpu_library_mcp.providers.dspace.solr_client import SolrClient

BASE = "http://10.1.0.205:8088/solr"


@respx.mock
async def test_select_success():
    respx.get(f"{BASE}/search/select").mock(
        return_value=httpx.Response(200, json={"response": {"numFound": 1, "docs": []}})
    )
    client = SolrClient(base_url=BASE, core="search")
    try:
        result = await client.select([("q", "*:*")])
    finally:
        await client.aclose()
    assert result["response"]["numFound"] == 1


@respx.mock
async def test_select_400_raises_solr_bad_request_error():
    respx.get(f"{BASE}/search/select").mock(return_value=httpx.Response(400))
    client = SolrClient(base_url=BASE, core="search")
    try:
        with pytest.raises(SolrBadRequestError):
            await client.select([("q", "*:*"), ("hl.fl", "khong_ton_tai")])
    finally:
        await client.aclose()


@respx.mock
async def test_select_500_raises_upstream_error():
    respx.get(f"{BASE}/search/select").mock(return_value=httpx.Response(500))
    client = SolrClient(base_url=BASE, core="search")
    try:
        with pytest.raises(UpstreamError):
            await client.select([("q", "*:*")])
    finally:
        await client.aclose()


@respx.mock
async def test_select_timeout_raises_upstream_error():
    respx.get(f"{BASE}/search/select").mock(side_effect=httpx.TimeoutException("timeout"))
    client = SolrClient(base_url=BASE, core="search")
    try:
        with pytest.raises(UpstreamError):
            await client.select([("q", "*:*")])
    finally:
        await client.aclose()


@respx.mock
async def test_select_sends_repeated_query_params():
    route = respx.get(f"{BASE}/search/select").mock(
        return_value=httpx.Response(200, json={"response": {"numFound": 0, "docs": []}})
    )
    client = SolrClient(base_url=BASE, core="search")
    try:
        await client.select([("fq", "a:1"), ("fq", "b:2")])
    finally:
        await client.aclose()
    sent_url = route.calls.last.request.url
    assert str(sent_url).count("fq=") == 2
