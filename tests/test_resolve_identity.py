from __future__ import annotations

import pytest

from hpu_library_mcp.errors import ForbiddenError
from hpu_library_mcp.security.keys import StaticApiKeyStore
from hpu_library_mcp.security.resolve import STDIO_LOCAL_KEY_ID, STDIO_LOCAL_SCOPE, resolve_identity
from tests.conftest import FakeContext, FakeRequest, http_ctx, stdio_ctx


async def test_stdio_no_request_is_trusted_internal():
    identity = await resolve_identity(stdio_ctx(), key_store=None)
    assert identity.key_id == STDIO_LOCAL_KEY_ID
    assert identity.scope == STDIO_LOCAL_SCOPE
    assert identity.allowed_levels == ("public", "internal", "restricted")


async def test_http_without_authorization_header_is_forbidden():
    with pytest.raises(ForbiddenError):
        await resolve_identity(http_ctx(), key_store=None)


async def test_http_with_key_but_no_key_store_configured_is_forbidden():
    with pytest.raises(ForbiddenError):
        await resolve_identity(http_ctx(bearer_token="any-key"), key_store=None)


async def test_http_with_invalid_key_is_forbidden():
    store = StaticApiKeyStore(raw_key="valid-key", scope="partner")
    with pytest.raises(ForbiddenError):
        await resolve_identity(http_ctx(bearer_token="wrong-key"), key_store=store)


async def test_http_with_valid_partner_key_resolves_public_only():
    store = StaticApiKeyStore(raw_key="partner-key", scope="partner", rate_limit=30)
    identity = await resolve_identity(http_ctx(bearer_token="partner-key"), key_store=store)
    assert identity.scope == "partner"
    assert identity.allowed_levels == ("public",)
    assert identity.rate_limit == 30


async def test_http_with_valid_internal_key_resolves_all_levels():
    store = StaticApiKeyStore(raw_key="internal-key", scope="internal")
    identity = await resolve_identity(http_ctx(bearer_token="internal-key"), key_store=store)
    assert identity.scope == "internal"
    assert set(identity.allowed_levels) == {"public", "internal", "restricted"}


async def test_header_key_lookup_is_case_insensitive():
    store = StaticApiKeyStore(raw_key="k", scope="internal")
    ctx = FakeContext(FakeRequest(headers={"Authorization": "Bearer k"}))
    identity = await resolve_identity(ctx, key_store=store)
    assert identity.scope == "internal"


async def test_bearer_prefix_case_insensitive():
    store = StaticApiKeyStore(raw_key="k", scope="internal")
    ctx = FakeContext(FakeRequest(headers={"authorization": "bearer k"}))
    identity = await resolve_identity(ctx, key_store=store)
    assert identity.scope == "internal"
