"""Giải quyết (key_id, scope, allowed_levels, rate_limit) cho 1 lượt gọi tool.

Quy tắc CỐ ĐỊNH theo transport (xem 01-requirements.md bảng actor, 05-security.md §2-3):
  - stdio: FastMCP Context.request_context.request là None (không có HTTP request) ->
    1 tiến trình phục vụ đúng 1 client cục bộ (Claude Code/Desktop của anh Trung) ->
    coi là "internal" cục bộ, không cần key.
  - streamable-http: request KHÔNG None -> LUÔN bắt buộc header
    `Authorization: Bearer <key>` hợp lệ, không có ngoại lệ.
Đã xác nhận `ctx.request_context.request` là kiểu `starlette.requests.Request | None`
bằng cách đọc trực tiếp mã nguồn gói `mcp` đã cài (không đoán).
"""

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.fastmcp import Context

from hpu_library_mcp.errors import ForbiddenError
from hpu_library_mcp.models import AccessLevel
from hpu_library_mcp.security.keys import SCOPE_ALLOWED_LEVELS, ApiKeyStore

STDIO_LOCAL_KEY_ID = "stdio-local"
STDIO_LOCAL_SCOPE = "internal"


@dataclass(frozen=True)
class ResolvedIdentity:
    key_id: str
    scope: str
    allowed_levels: tuple[AccessLevel, ...]
    rate_limit: int | None


def _extract_bearer_token(ctx: Context) -> str | None:
    request = ctx.request_context.request
    if request is None:
        return None
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    return header[len("bearer ") :].strip()


async def resolve_identity(ctx: Context, *, key_store: ApiKeyStore | None) -> ResolvedIdentity:
    is_http_request = ctx.request_context.request is not None

    if not is_http_request:
        return ResolvedIdentity(
            key_id=STDIO_LOCAL_KEY_ID,
            scope=STDIO_LOCAL_SCOPE,
            allowed_levels=SCOPE_ALLOWED_LEVELS[STDIO_LOCAL_SCOPE],
            rate_limit=None,
        )

    token = _extract_bearer_token(ctx)
    if not token:
        raise ForbiddenError("Thiếu API key (header Authorization: Bearer <key>).")
    if key_store is None:
        raise ForbiddenError("Server chưa cấu hình API key — từ chối mọi request qua streamable-http.")

    record = await key_store.resolve(token)
    if record is None:
        raise ForbiddenError("API key không hợp lệ hoặc đã bị khóa.")

    return ResolvedIdentity(
        key_id=record.id, scope=record.scope, allowed_levels=record.allowed_levels, rate_limit=record.rate_limit
    )
