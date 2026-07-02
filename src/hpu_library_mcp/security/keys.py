"""API key -> scope -> allowed_levels — xem 04-data-model.md §3, 05-security.md §2-3.

Ánh xạ scope -> allowed_levels là BẤT BIẾN của hệ thống (05-security.md §3), đặt ở đây
làm nguồn chân lý duy nhất — không lặp lại chỗ khác.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from hpu_library_mcp.db import Database
from hpu_library_mcp.models import ALL_ACCESS_LEVELS, AccessLevel

Scope = Literal["internal", "partner"]

SCOPE_ALLOWED_LEVELS: dict[Scope, tuple[AccessLevel, ...]] = {
    "partner": ("public",),
    "internal": ALL_ACCESS_LEVELS,
}


def hash_api_key(raw_key: str) -> str:
    """Không lưu key thô — chỉ lưu/so khớp hash (05-security.md §2)."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ApiKeyRecord:
    id: str
    scope: Scope
    label: str | None = None
    rate_limit: int | None = None

    @property
    def allowed_levels(self) -> tuple[AccessLevel, ...]:
        return SCOPE_ALLOWED_LEVELS[self.scope]


class ApiKeyStore(ABC):
    @abstractmethod
    async def resolve(self, raw_key: str) -> ApiKeyRecord | None:
        """Trả record nếu key hợp lệ VÀ active; None nếu sai/không tồn tại/bị khóa
        (fail-safe: mọi trường hợp mơ hồ đều coi như không hợp lệ, không đoán quyền)."""


class PostgresApiKeyStore(ApiKeyStore):
    def __init__(self, database: Database) -> None:
        self._db = database

    async def resolve(self, raw_key: str) -> ApiKeyRecord | None:
        key_hash = hash_api_key(raw_key)
        pool = await self._db.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, scope, label, rate_limit, active FROM api_keys WHERE key_hash = $1", key_hash
            )
        if row is None or not row["active"]:
            return None
        if row["scope"] not in SCOPE_ALLOWED_LEVELS:
            return None  # scope lạ trong DB -> coi như không hợp lệ (fail-safe)
        return ApiKeyRecord(id=row["id"], scope=row["scope"], label=row["label"], rate_limit=row["rate_limit"])


class StaticApiKeyStore(ApiKeyStore):
    """Fallback khi CHƯA cấu hình DATABASE_URL — 1 key tĩnh đọc từ `.env` (dev/demo).

    KHÔNG dùng cho production nhiều client — chỉ để chạy thử streamable-http khi chưa
    cắm Postgres `api_keys` thật (xem docs/DECISIONS.md Sprint 4).
    """

    def __init__(self, *, raw_key: str, scope: Scope, rate_limit: int | None = None) -> None:
        self._key_hash = hash_api_key(raw_key) if raw_key else None
        self._scope = scope
        self._rate_limit = rate_limit

    async def resolve(self, raw_key: str) -> ApiKeyRecord | None:
        if not self._key_hash or not raw_key or hash_api_key(raw_key) != self._key_hash:
            return None
        return ApiKeyRecord(id="dev-static", scope=self._scope, label="dev static key", rate_limit=self._rate_limit)
