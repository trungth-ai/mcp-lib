from __future__ import annotations

from hpu_library_mcp.security.keys import (
    SCOPE_ALLOWED_LEVELS,
    PostgresApiKeyStore,
    StaticApiKeyStore,
    hash_api_key,
)
from tests.conftest import FakeAsyncpgConn, FakeDatabase


def test_scope_allowed_levels_partner_is_public_only():
    assert SCOPE_ALLOWED_LEVELS["partner"] == ("public",)


def test_scope_allowed_levels_internal_sees_all():
    assert set(SCOPE_ALLOWED_LEVELS["internal"]) == {"public", "internal", "restricted"}


def test_hash_api_key_deterministic_and_not_reversible_looking():
    h1 = hash_api_key("secret-key-123")
    h2 = hash_api_key("secret-key-123")
    assert h1 == h2
    assert h1 != "secret-key-123"
    assert len(h1) == 64  # sha256 hex


def test_hash_api_key_different_keys_different_hash():
    assert hash_api_key("key-a") != hash_api_key("key-b")


# --- StaticApiKeyStore ---


async def test_static_key_store_resolves_matching_key():
    store = StaticApiKeyStore(raw_key="partner-secret", scope="partner", rate_limit=30)
    record = await store.resolve("partner-secret")
    assert record is not None
    assert record.scope == "partner"
    assert record.allowed_levels == ("public",)
    assert record.rate_limit == 30


async def test_static_key_store_rejects_wrong_key():
    store = StaticApiKeyStore(raw_key="partner-secret", scope="partner")
    assert await store.resolve("khong-dung") is None


async def test_static_key_store_rejects_empty_key():
    store = StaticApiKeyStore(raw_key="partner-secret", scope="partner")
    assert await store.resolve("") is None


async def test_static_key_store_unconfigured_rejects_everything():
    store = StaticApiKeyStore(raw_key="", scope="partner")
    assert await store.resolve("bat-ky-key-nao") is None


# --- PostgresApiKeyStore (fake pool, không cần Postgres thật) ---


async def test_postgres_key_store_resolves_active_key():
    row = {"id": "key-1", "scope": "internal", "label": "RAG chatbot", "rate_limit": 100, "active": True}
    store = PostgresApiKeyStore(FakeDatabase(FakeAsyncpgConn(fetchrow_result=row)))
    record = await store.resolve("raw-key")
    assert record is not None
    assert record.id == "key-1"
    assert record.allowed_levels == SCOPE_ALLOWED_LEVELS["internal"]


async def test_postgres_key_store_rejects_inactive_key():
    row = {"id": "key-1", "scope": "internal", "label": None, "rate_limit": None, "active": False}
    store = PostgresApiKeyStore(FakeDatabase(FakeAsyncpgConn(fetchrow_result=row)))
    assert await store.resolve("raw-key") is None


async def test_postgres_key_store_rejects_unknown_key():
    store = PostgresApiKeyStore(FakeDatabase(FakeAsyncpgConn(fetchrow_result=None)))
    assert await store.resolve("khong-ton-tai") is None


async def test_postgres_key_store_rejects_unknown_scope_fail_safe():
    row = {"id": "key-1", "scope": "super-admin", "label": None, "rate_limit": None, "active": True}
    store = PostgresApiKeyStore(FakeDatabase(FakeAsyncpgConn(fetchrow_result=row)))
    assert await store.resolve("raw-key") is None


async def test_postgres_key_store_queries_by_hash_not_raw_key():
    conn = FakeAsyncpgConn(fetchrow_result=None)
    store = PostgresApiKeyStore(FakeDatabase(conn))
    await store.resolve("raw-key-nhay-cam")
    _, args = conn.executed[0]
    assert "raw-key-nhay-cam" not in args
    assert args[0] == hash_api_key("raw-key-nhay-cam")
