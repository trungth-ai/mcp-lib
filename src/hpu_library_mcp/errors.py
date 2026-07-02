from __future__ import annotations

from typing import Any


class McpToolError(Exception):
    """Lỗi có cấu trúc, an toàn để trả thẳng cho client MCP.

    message phải là tiếng Việt, dành cho người dùng cuối, KHÔNG chứa chi tiết nội bộ
    (host, stack trace, token...) — xem 03-tools-spec.md và NFR-2.
    """

    code = "INTERNAL_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code

    def to_response(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message}}


class NotFoundError(McpToolError):
    code = "NOT_FOUND"


class ForbiddenError(McpToolError):
    """Key không đủ quyền xem tài liệu này — PHẢI đi kèm ghi audit ở nơi gọi."""

    code = "FORBIDDEN"

    def __init__(self, message: str = "Bạn không có quyền truy cập tài liệu này.") -> None:
        super().__init__(message)


class ValidationError(McpToolError):
    code = "VALIDATION_ERROR"


class UpstreamError(McpToolError):
    """Lỗi khi gọi DSpace REST/Solr. Không bao giờ nhét exception gốc vào message."""

    code = "UPSTREAM_ERROR"

    def __init__(self, message: str = "Không thể lấy dữ liệu từ hệ thống thư viện lúc này.") -> None:
        super().__init__(message)


class SolrBadRequestError(UpstreamError):
    """Solr trả 400 (thường do tên field cấu hình sai) — caller có thể thử suy biến.

    Khác UpstreamError thường (5xx/timeout/mạng) ở chỗ đây là lỗi CẤU HÌNH (field không
    tồn tại), không phải Solr đang down — nơi gọi có thể thử lại bớt tham số thay vì coi
    là toàn bộ Solr chết.
    """

    code = "UPSTREAM_ERROR"


class NotImplementedYetError(McpToolError):
    code = "NOT_IMPLEMENTED"

    def __init__(self, feature: str, sprint: str) -> None:
        super().__init__(f"Chức năng '{feature}' chưa được triển khai (dự kiến {sprint}).")


def to_error_response(exc: Exception) -> dict[str, Any]:
    """Chuẩn hóa mọi exception thành {"error": {"code","message"}}.

    Exception không xác định (bug, lỗi thư viện...) bị che thành thông báo chung —
    chi tiết thật chỉ đi vào log server-side (xem logging_setup.py), tránh lộ nội bộ.
    """
    if isinstance(exc, McpToolError):
        return exc.to_response()
    return {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "Đã có lỗi xảy ra. Vui lòng thử lại sau.",
        }
    }
