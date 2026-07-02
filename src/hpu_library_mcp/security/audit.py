"""Audit riêng cho truy cập tài liệu internal/restricted — 05-security.md §6, bất biến #1.

Ghi key-id + item-id + kết quả (cho/từ chối) cho MỌI lần chạm tài liệu không phải public,
bất kể có tầng auth thật hay chưa (khi chưa có, key-id là placeholder "-" từ logging_setup).
"""

from __future__ import annotations

from hpu_library_mcp.logging_setup import current_key_id, get_logger
from hpu_library_mcp.models import AccessLevel

_audit_logger = get_logger("hpu_library_mcp.audit")


def audit_access(*, item_id: str, access_level: AccessLevel, granted: bool) -> None:
    if access_level == "public":
        return  # 05-security.md §6: chỉ audit truy cập internal/restricted
    _audit_logger.info(
        "audit key_id=%s item_id=%s access_level=%s granted=%s",
        current_key_id(),
        item_id,
        access_level,
        granted,
    )
