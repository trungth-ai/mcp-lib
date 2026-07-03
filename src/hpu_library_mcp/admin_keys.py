"""CLI quản lý `api_keys` — chạy trực tiếp trên Postgres, không qua MCP tool nào (đây là
việc vận hành/anh Trung, không phải chức năng cho client AI gọi) — xem 07-sprints.md
Sprint 5 "hướng dẫn rotate key".

Dùng:
    python -m hpu_library_mcp.admin_keys create --label "RAG chatbot" --scope internal
    python -m hpu_library_mcp.admin_keys list
    python -m hpu_library_mcp.admin_keys revoke <key_id>

Key thô CHỈ hiện ra đúng 1 lần lúc `create` — không lưu lại ở đâu (chỉ lưu hash trong DB,
xem 05-security.md §2).
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
from datetime import datetime, timezone

from hpu_library_mcp.config import get_settings
from hpu_library_mcp.db import Database
from hpu_library_mcp.security.keys import SCOPE_ALLOWED_LEVELS, hash_api_key


async def _create(database: Database, *, label: str, scope: str, rate_limit: int | None) -> None:
    raw_key = secrets.token_urlsafe(32)
    key_id = f"key_{secrets.token_hex(6)}"
    pool = await database.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO api_keys (id, key_hash, label, scope, rate_limit, active, created_at) "
            "VALUES ($1, $2, $3, $4, $5, true, $6)",
            key_id,
            hash_api_key(raw_key),
            label,
            scope,
            rate_limit,
            datetime.now(timezone.utc),
        )
    print(f"Đã tạo key id={key_id} scope={scope} label={label!r}")
    print(f"KEY THÔ (chỉ hiện 1 lần, chép lại ngay): {raw_key}")


async def _list(database: Database) -> None:
    pool = await database.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, label, scope, rate_limit, active, created_at FROM api_keys ORDER BY created_at DESC"
        )
    if not rows:
        print("(chưa có key nào)")
        return
    for row in rows:
        state = "active" if row["active"] else "REVOKED"
        print(
            f"{row['id']}  scope={row['scope']:<8}  {state:<8}  rate_limit={row['rate_limit']}  "
            f"label={row['label']!r}  created_at={row['created_at']}"
        )


async def _revoke(database: Database, key_id: str) -> None:
    pool = await database.get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("UPDATE api_keys SET active = false WHERE id = $1", key_id)
    if result == "UPDATE 0":
        print(f"Không tìm thấy key id={key_id}", file=sys.stderr)
        sys.exit(1)
    print(f"Đã khóa (revoke) key id={key_id}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m hpu_library_mcp.admin_keys")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="Tạo key mới")
    create.add_argument("--label", required=True, help="Tên gợi nhớ, vd 'RAG chatbot'")
    create.add_argument("--scope", required=True, choices=sorted(SCOPE_ALLOWED_LEVELS))
    create.add_argument("--rate-limit", type=int, default=None, help="Số request/phút, mặc định dùng cấu hình chung")

    sub.add_parser("list", help="Liệt kê toàn bộ key")

    revoke = sub.add_parser("revoke", help="Khóa 1 key (soft — không xóa hẳn)")
    revoke.add_argument("key_id")

    return parser


async def _run(args: argparse.Namespace) -> None:
    settings = get_settings()
    if not settings.database_url:
        raise SystemExit("Cần DATABASE_URL trong .env để quản lý api_keys.")
    database = Database(settings.database_url)
    await database.ensure_schema(embedding_dimensions=settings.gemini_embedding_dimensions)
    try:
        if args.command == "create":
            await _create(database, label=args.label, scope=args.scope, rate_limit=args.rate_limit)
        elif args.command == "list":
            await _list(database)
        elif args.command == "revoke":
            await _revoke(database, args.key_id)
    finally:
        await database.aclose()


def main() -> None:
    args = _build_parser().parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
