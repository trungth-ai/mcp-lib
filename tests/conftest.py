from __future__ import annotations

from typing import Any

import pytest

from hpu_library_mcp.config import get_settings


@pytest.fixture(autouse=True)
def _pin_dspace_version_for_legacy_suite(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ghim DSPACE_VERSION=6.3 cho toàn bộ test cũ (chúng inject fake client REST 6.x).

    Từ 2026-07-14 HPU lên DSpace 7.6 nên `.env` thật đặt DSPACE_VERSION=7.6 -> `Settings()`
    trần sẽ chọn adapter v7 (bỏ qua fake v6 -> gọi mạng thật). Biến môi trường OS ưu tiên
    HƠN file `.env` trong pydantic-settings, nên đặt ở đây khiến mọi `Settings()` trần trong
    test quay về 6.3 BẤT KỂ `.env`. Test v7 mới truyền thẳng `Settings(dspace_version="7.6")`
    (init kwarg ưu tiên hơn cả env var) nên không bị ảnh hưởng. Fixture CHỈ thêm tính tất
    định, không đổi assertion của test nào."""
    monkeypatch.setenv("DSPACE_VERSION", "6.3")
    get_settings.cache_clear()

SAMPLE_ITEM: dict[str, Any] = {
    "uuid": "item-uuid-1",
    "handle": "123456789/42",
    "name": "Ứng dụng học máy trong dự báo tuyển sinh",
    "metadata": [
        {"key": "dc.title", "value": "Ứng dụng học máy trong dự báo tuyển sinh", "language": None},
        {"key": "dc.contributor.author", "value": "Nguyễn Văn A", "language": None},
        {"key": "dc.contributor.author", "value": "Trần Thị B", "language": None},
        {"key": "dc.date.issued", "value": "2023-05-01", "language": None},
        {"key": "dc.date.accessioned", "value": "2023-06-01T00:00:00Z", "language": None},
        {"key": "dc.type", "value": "Thesis", "language": None},
        {"key": "dc.language.iso", "value": "vi", "language": None},
        {"key": "dc.description.abstract", "value": "Luận văn nghiên cứu ứng dụng học máy...", "language": None},
    ],
    "parentCollection": {"uuid": "col-1", "name": "Luận văn Thạc sĩ"},
    "parentCommunityList": [{"uuid": "comm-1", "name": "Khoa CNTT"}],
    "bitstreams": [
        {
            "uuid": "bit-1",
            "name": "toanvan.pdf",
            "bundleName": "ORIGINAL",
            "mimeType": "application/pdf",
            "sizeBytes": 2451234,
            "retrieveLink": "/bitstreams/bit-1/retrieve",
        },
        {
            "uuid": "bit-license",
            "name": "license.txt",
            "bundleName": "LICENSE",
            "mimeType": "text/plain",
            "sizeBytes": 100,
            "retrieveLink": "/bitstreams/bit-license/retrieve",
        },
    ],
}

ANON_READ_POLICY = [{"action": "READ", "groupId": 0}]
INTERNAL_READ_POLICY = [{"action": "READ", "groupId": 5}]
NO_READ_POLICY: list[dict[str, Any]] = []
FUTURE_EMBARGO_POLICY = [{"action": "READ", "groupId": 0, "startDate": "2999-01-01"}]
EXPIRED_POLICY = [{"action": "READ", "groupId": 0, "endDate": "2000-01-01"}]


class FakeDSpaceRestClient:
    """Thay thế DSpaceRestClient thật cho test provider — không gọi HTTP."""

    def __init__(self, routes: dict[str, Any]) -> None:
        self._routes = routes
        self.calls: list[str] = []

    async def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return self._resolve(path)

    async def get_bytes(self, path: str, *, params: dict[str, Any] | None = None) -> bytes:
        return self._resolve(path)

    def _resolve(self, path: str) -> Any:
        self.calls.append(path)
        if path not in self._routes:
            raise AssertionError(f"FakeDSpaceRestClient: route chưa mock cho {path}")
        value = self._routes[path]
        if isinstance(value, Exception):
            raise value
        return value

    async def aclose(self) -> None:
        pass


class FakeSolrClient:
    """Thay thế SolrClient thật cho test provider — không gọi HTTP.

    `responses` là 1 raw response (dùng cho mọi lần gọi) hoặc list các response/exception
    trả tuần tự theo từng lần select() (dùng để test retry/suy biến).
    """

    def __init__(self, responses: Any) -> None:
        self._responses = responses if isinstance(responses, list) else [responses]
        self.calls: list[list[tuple[str, Any]]] = []

    async def select(self, params: list[tuple[str, Any]]) -> Any:
        self.calls.append(params)
        index = min(len(self.calls) - 1, len(self._responses) - 1)
        value = self._responses[index]
        if isinstance(value, Exception):
            raise value
        return value

    async def aclose(self) -> None:
        pass


def solr_params_dict(params: list[tuple[str, Any]]) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for key, value in params:
        out.setdefault(key, []).append(value)
    return out


@pytest.fixture
def sample_item() -> dict[str, Any]:
    import copy

    return copy.deepcopy(SAMPLE_ITEM)


# --- Fakes cho asyncpg (VectorStore/PostgresApiKeyStore) — không cần Postgres thật ---


class _FakeTransaction:
    async def __aenter__(self) -> "_FakeTransaction":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class FakeAsyncpgConn:
    def __init__(self, *, fetch_result: list[Any] | None = None, fetchrow_result: Any = None) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self._fetch_result = fetch_result if fetch_result is not None else []
        self._fetchrow_result = fetchrow_result

    async def execute(self, sql: str, *args: Any) -> str:
        self.executed.append((sql, args))
        return "OK"

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        self.executed.append((sql, args))
        return self._fetch_result

    async def fetchrow(self, sql: str, *args: Any) -> Any:
        self.executed.append((sql, args))
        return self._fetchrow_result

    def transaction(self) -> _FakeTransaction:
        return _FakeTransaction()


class _FakeAcquire:
    def __init__(self, conn: FakeAsyncpgConn) -> None:
        self._conn = conn

    async def __aenter__(self) -> FakeAsyncpgConn:
        return self._conn

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class FakeAsyncpgPool:
    def __init__(self, conn: FakeAsyncpgConn) -> None:
        self._conn = conn

    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire(self._conn)


class FakeDatabase:
    """Thay thế db.Database — get_pool() trả FakeAsyncpgPool, không kết nối thật."""

    def __init__(self, conn: FakeAsyncpgConn) -> None:
        self.conn = conn
        self._pool = FakeAsyncpgPool(conn)

    async def get_pool(self) -> FakeAsyncpgPool:
        return self._pool

    async def connect(self) -> None:
        pass

    async def aclose(self) -> None:
        pass


# --- Fakes cho vector layer (Sprint 3) ---


class FakeEmbeddingProvider:
    def __init__(self, vector: list[float] | None = None, dimensions: int = 3) -> None:
        self.dimensions = dimensions
        self._vector = vector or [0.1, 0.2, 0.3]
        self.calls: list[tuple[list[str], str]] = []

    async def embed(self, texts: list[str], *, task_type: str) -> list[list[float]]:
        self.calls.append((texts, task_type))
        return [list(self._vector) for _ in texts]


class FakeVectorStore:
    def __init__(self, chunks: list[Any] | None = None) -> None:
        self._chunks = chunks or []
        self.search_calls: list[dict[str, Any]] = []
        self.upserted: list[Any] = []
        self.sync_states: list[dict[str, Any]] = []

    async def semantic_search(
        self, *, embedding: list[float], source: str, allowed_levels: tuple[str, ...], k: int
    ) -> list[Any]:
        self.search_calls.append(
            {"embedding": embedding, "source": source, "allowed_levels": allowed_levels, "k": k}
        )
        return self._chunks

    async def upsert_chunks(self, chunks: list[Any]) -> None:
        self.upserted.extend(chunks)

    async def set_sync_state(
        self, *, source: str, last_synced_at: Any, last_item_ts: Any, notes: str | None = None
    ) -> None:
        self.sync_states.append(
            {"source": source, "last_synced_at": last_synced_at, "last_item_ts": last_item_ts, "notes": notes}
        )


# --- Fakes cho FastMCP Context (security/resolve.py) — không dựng Context thật của SDK ---


class FakeHeaders(dict):
    def get(self, key: str, default: Any = None) -> Any:  # header lookup không phân biệt hoa/thường
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default


class FakeRequest:
    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = FakeHeaders(headers or {})


class FakeRequestContext:
    def __init__(self, request: FakeRequest | None) -> None:
        self.request = request


class FakeContext:
    """Duck-type ctx.request_context.request — đủ cho security/resolve.py, không cần
    dựng mcp.server.fastmcp.Context thật (phụ thuộc session/transport nội bộ của SDK)."""

    def __init__(self, request: FakeRequest | None) -> None:
        self.request_context = FakeRequestContext(request)


def http_ctx(*, bearer_token: str | None = None) -> FakeContext:
    headers = {"authorization": f"Bearer {bearer_token}"} if bearer_token else {}
    return FakeContext(FakeRequest(headers=headers))


def stdio_ctx() -> FakeContext:
    return FakeContext(request=None)


# 1 trang, chữ "Hello World" — dùng để test bóc text PDF không cần file thật.
MINIMAL_PDF_BYTES = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/Resources<</Font<</F1 4 0 R>>>>/MediaBox[0 0 200 200]/Contents 5 0 R>>endobj
4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
5 0 obj<</Length 44>>stream
BT /F1 24 Tf 10 100 Td (Hello World) Tj ET
endstream
endobj
trailer<</Size 6/Root 1 0 R>>
%%EOF"""
