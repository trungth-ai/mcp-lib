from __future__ import annotations

import pytest

from hpu_library_mcp.config import Settings
from hpu_library_mcp.errors import ForbiddenError, NotFoundError
from hpu_library_mcp.providers.dspace.provider import DSpaceProvider
from tests.conftest import ANON_READ_POLICY, INTERNAL_READ_POLICY, MINIMAL_PDF_BYTES, FakeDSpaceRestClient

REST_BASE = "http://10.1.0.205:8088/rest"
BITSTREAM_URL = f"{REST_BASE}/bitstreams/bit-1/retrieve"


def make_provider(routes: dict) -> DSpaceProvider:
    return DSpaceProvider(settings=Settings(), client=FakeDSpaceRestClient(routes))


async def test_get_text_returns_pages_for_public_item(sample_item):
    provider = make_provider(
        {
            "/handle/123456789/42": sample_item,
            "/items/item-uuid-1/policy": ANON_READ_POLICY,
            BITSTREAM_URL: MINIMAL_PDF_BYTES,
        }
    )
    doc = await provider.get_text("123456789/42")
    assert doc.access_level == "public"
    assert doc.pages[0].text == "Hello World"
    assert doc.pages[0].page == 1


async def test_get_text_forbidden_for_partner_on_restricted_item(sample_item):
    provider = make_provider(
        {
            "/handle/123456789/42": sample_item,
            "/items/item-uuid-1/policy": INTERNAL_READ_POLICY,
        }
    )
    with pytest.raises(ForbiddenError):
        await provider.get_text("123456789/42", allowed_levels=("public",))


async def test_get_text_allowed_for_internal_on_restricted_item(sample_item):
    provider = make_provider(
        {
            "/handle/123456789/42": sample_item,
            "/items/item-uuid-1/policy": INTERNAL_READ_POLICY,
            BITSTREAM_URL: MINIMAL_PDF_BYTES,
        }
    )
    doc = await provider.get_text("123456789/42", allowed_levels=("public", "internal", "restricted"))
    assert doc.access_level == "internal"
    assert doc.pages[0].text == "Hello World"


async def test_get_text_no_pdf_bitstream_raises_not_found(sample_item):
    sample_item["bitstreams"] = [
        {
            "uuid": "bit-txt",
            "name": "readme.txt",
            "bundleName": "ORIGINAL",
            "mimeType": "text/plain",
            "sizeBytes": 10,
            "retrieveLink": "/bitstreams/bit-txt/retrieve",
        }
    ]
    provider = make_provider(
        {"/handle/123456789/42": sample_item, "/items/item-uuid-1/policy": ANON_READ_POLICY}
    )
    with pytest.raises(NotFoundError):
        await provider.get_text("123456789/42")


async def test_get_text_with_query_returns_only_matching_pages(sample_item):
    provider = make_provider(
        {
            "/handle/123456789/42": sample_item,
            "/items/item-uuid-1/policy": ANON_READ_POLICY,
            BITSTREAM_URL: MINIMAL_PDF_BYTES,
        }
    )
    doc = await provider.get_text("123456789/42", query="Hello")
    assert len(doc.pages) == 1
    assert doc.pages[0].matches

    doc_no_match = await provider.get_text("123456789/42", query="không tồn tại trong tài liệu")
    assert doc_no_match.pages == []


async def test_get_text_with_page_out_of_range_returns_empty_pages(sample_item):
    provider = make_provider(
        {
            "/handle/123456789/42": sample_item,
            "/items/item-uuid-1/policy": ANON_READ_POLICY,
            BITSTREAM_URL: MINIMAL_PDF_BYTES,
        }
    )
    doc = await provider.get_text("123456789/42", page=99)
    assert doc.pages == []


async def test_get_text_ambiguous_access_treated_as_restricted_and_forbidden(sample_item):
    # Không lấy được policy (route không mock -> lỗi) -> infer_access_level trả restricted.
    provider = make_provider({"/handle/123456789/42": sample_item, "/items/item-uuid-1/policy": []})
    with pytest.raises(ForbiddenError):
        await provider.get_text("123456789/42", allowed_levels=("public",))
