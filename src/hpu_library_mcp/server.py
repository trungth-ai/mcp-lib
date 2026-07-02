"""FastMCP server — HPU Library MCP (Sprint 1: lõi + tools metadata DSpace 6.3).

Tools hiện có: get_item, list_communities, list_collections, get_recent_items,
get_bitstream_link — theo đúng I/O của 03-tools-spec.md.

Sprint 1 CHƯA có tầng auth/API key (xem 05-security.md, Sprint 4) — mọi tool chạy
không giới hạn allowed_levels. KHÔNG expose ra Internet ở trạng thái này.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from mcp.server.fastmcp import FastMCP

from hpu_library_mcp.config import get_settings
from hpu_library_mcp.errors import McpToolError, to_error_response
from hpu_library_mcp.logging_setup import configure_logging, get_logger, tool_call_context
from hpu_library_mcp.models import NodeList
from hpu_library_mcp.providers.dspace.provider import DSpaceProvider
from hpu_library_mcp.providers.registry import ProviderRegistry

logger = get_logger(__name__)

mcp = FastMCP("hpu-library-mcp")

_registry: ProviderRegistry | None = None


def get_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        settings = get_settings()
        registry = ProviderRegistry()
        registry.register(DSpaceProvider(settings=settings))
        _registry = registry
    return _registry


F = TypeVar("F", bound=Callable[..., Awaitable[dict[str, Any]]])


def _handle_errors(tool_name: str) -> Callable[[F], F]:
    """Bọc mỗi tool: gắn request-id/latency log, chặn exception rò rỉ chi tiết nội bộ.

    Xem 03-tools-spec.md ("Lỗi trả cấu trúc {error:{code,message}}, không lộ chi tiết").
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            with tool_call_context(tool_name):
                try:
                    return await fn(*args, **kwargs)
                except McpToolError as exc:
                    return exc.to_response()
                except Exception as exc:  # noqa: BLE001 - cố ý chặn mọi lỗi không lường trước
                    logger.exception("unhandled_tool_error")
                    return to_error_response(exc)

        return wrapper  # type: ignore[return-value]

    return decorator


@mcp.tool()
@_handle_errors("get_item")
async def get_item(id: str, source: str = "dspace") -> dict[str, Any]:
    """Lấy metadata Dublin Core chuẩn hóa + danh sách bitstream của 1 tài liệu thư viện."""
    provider = get_registry().get(source)
    resource = await provider.get(id)
    return resource.model_dump(mode="json")


@mcp.tool()
@_handle_errors("list_communities")
async def list_communities(parent: str | None = None, source: str = "dspace") -> dict[str, Any]:
    """Liệt kê cây đơn vị (communities) của thư viện. Không truyền parent -> danh sách gốc."""
    provider = get_registry().get(source)
    nodes = await provider.list_communities(parent=parent)
    return NodeList(nodes=nodes).model_dump(mode="json")


@mcp.tool()
@_handle_errors("list_collections")
async def list_collections(parent: str | None = None, source: str = "dspace") -> dict[str, Any]:
    """Liệt kê bộ sưu tập (collections). Truyền parent = id community để lọc theo đơn vị."""
    provider = get_registry().get(source)
    nodes = await provider.list_collections(parent=parent)
    return NodeList(nodes=nodes).model_dump(mode="json")


@mcp.tool()
@_handle_errors("get_recent_items")
async def get_recent_items(
    collection: str | None = None, limit: int = 10, source: str = "dspace"
) -> dict[str, Any]:
    """Lấy danh sách tài liệu mới nạp gần đây, sắp xếp giảm dần theo ngày nạp."""
    provider = get_registry().get(source)
    resources = await provider.get_recent_items(collection=collection, limit=limit)
    return {"items": [r.model_dump(mode="json") for r in resources]}


@mcp.tool()
@_handle_errors("get_bitstream_link")
async def get_bitstream_link(item_id: str, bitstream_id: str, source: str = "dspace") -> dict[str, Any]:
    """Lấy link tải 1 tệp (bitstream) cụ thể của tài liệu, kèm mức truy cập yêu cầu."""
    provider = get_registry().get(source)
    link = await provider.get_bitstream_link(item_id, bitstream_id)
    return link.model_dump(mode="json")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("hpu_library_mcp_starting transport=%s", settings.mcp_transport)
    if settings.mcp_transport == "streamable-http":
        mcp.settings.host = settings.mcp_http_host
        mcp.settings.port = settings.mcp_http_port
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
