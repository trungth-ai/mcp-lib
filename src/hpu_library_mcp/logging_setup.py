from __future__ import annotations

import contextvars
import logging
import re
import time
import uuid
from collections.abc import Iterable
from contextlib import contextmanager

# --- Redaction (NFR-2 / 05-security.md §5-6: không rò rỉ token/mật khẩu vào log) ---

_GENERIC_SECRET_PATTERNS = [
    re.compile(r'(rest-dspace-token["\']?\s*[:=]\s*["\']?)([^"\'\s,}]+)', re.IGNORECASE),
    re.compile(r'(authorization["\']?\s*[:=]\s*["\']?bearer\s+)([^"\'\s,}]+)', re.IGNORECASE),
    re.compile(r'((?:password|passwd|secret|api[_-]?key|token)["\']?\s*[:=]\s*["\']?)([^"\'\s,}]+)', re.IGNORECASE),
]


def redact_text(text: str | None, extra_secrets: Iterable[str] | None = None) -> str | None:
    """Che token/mật khẩu trong một chuỗi log. An toàn khi text rỗng/None."""
    if not text:
        return text
    redacted = text
    for pattern in _GENERIC_SECRET_PATTERNS:
        redacted = pattern.sub(r"\1***REDACTED***", redacted)
    for secret in extra_secrets or ():
        if secret:
            redacted = redacted.replace(secret, "***REDACTED***")
    return redacted


def _current_secrets() -> list[str]:
    try:
        from hpu_library_mcp.config import get_settings

        settings = get_settings()
    except Exception:
        return []
    secrets: list[str] = []
    pw = settings.dspace_service_password.get_secret_value()
    if pw:
        secrets.append(pw)
    gk = settings.gemini_api_key.get_secret_value()
    if gk:
        secrets.append(gk)
    return secrets


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        redacted = redact_text(message, _current_secrets())
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


# --- Ngữ cảnh request (request-id, key-id, scope, tool) — xem NFR-6 ---

_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
_key_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("key_id", default="-")
_scope_var: contextvars.ContextVar[str] = contextvars.ContextVar("scope", default="-")
_tool_var: contextvars.ContextVar[str] = contextvars.ContextVar("tool", default="-")
# None = chưa nối auth (Sprint 1-3, không lọc) — KHÁC () rỗng (đã nối auth nhưng key
# không được phép thấy mức nào, vd scope lạ). Không nhầm 2 trạng thái này.
_allowed_levels_var: contextvars.ContextVar[tuple[str, ...] | None] = contextvars.ContextVar(
    "allowed_levels", default=None
)


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_var.get()
        record.key_id = _key_id_var.get()
        record.scope = _scope_var.get()
        record.tool = _tool_var.get()
        return True


_LOG_FORMAT = (
    "%(asctime)s %(levelname)s [rid=%(request_id)s key=%(key_id)s "
    "scope=%(scope)s tool=%(tool)s] %(name)s: %(message)s"
)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    handler.addFilter(ContextFilter())
    handler.addFilter(RedactionFilter())
    root.handlers = [handler]


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def current_key_id() -> str:
    """key-id của request hiện tại (đặt bởi tool_call_context) — dùng cho audit log."""
    return _key_id_var.get()


def current_scope() -> str:
    return _scope_var.get()


def current_request_id() -> str:
    return _request_id_var.get()


def current_allowed_levels() -> tuple[str, ...] | None:
    """allowed_levels đã resolve cho request hiện tại (đặt bởi tool_call_context).

    None = chưa nối auth (không lọc); tuple rỗng = đã nối auth nhưng key không có quyền
    thấy mức nào — provider phải phân biệt 2 trường hợp này (xem base.py).
    """
    return _allowed_levels_var.get()


@contextmanager
def tool_call_context(
    tool: str, key_id: str = "-", scope: str = "-", allowed_levels: tuple[str, ...] | None = None
):
    """Gắn request-id/key-id/scope/allowed_levels/tool vào mọi log + provider call trong
    1 lần gọi tool, đo latency. Dùng bao quanh mỗi tool trong server.py — xem NFR-6.
    """
    request_id = uuid.uuid4().hex[:12]
    tokens = (
        _request_id_var.set(request_id),
        _key_id_var.set(key_id),
        _scope_var.set(scope),
        _tool_var.set(tool),
        _allowed_levels_var.set(allowed_levels),
    )
    logger = get_logger("hpu_library_mcp.tool")
    started_at = time.monotonic()
    logger.info("tool_call_start")
    try:
        yield request_id
    except Exception:
        logger.exception("tool_call_error")
        raise
    finally:
        latency_ms = (time.monotonic() - started_at) * 1000
        logger.info("tool_call_end latency_ms=%.1f", latency_ms)
        for var, token in zip(
            (_request_id_var, _key_id_var, _scope_var, _tool_var, _allowed_levels_var), tokens
        ):
            var.reset(token)
