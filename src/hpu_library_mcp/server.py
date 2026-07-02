"""FastMCP server — HPU Library MCP.

10 tools: get_item, list_communities, list_collections, get_recent_items,
get_bitstream_link, search_library, library_stats, semantic_search_documents,
get_document_text, find_in_document — I/O khớp 03-tools-spec.md.

Phân quyền (Sprint 4, 05-security.md): MỌI tool nhận `ctx: Context` để resolve_identity()
suy ra (key_id, scope, allowed_levels) theo transport — xem security/resolve.py. stdio
(hoặc gọi trực tiếp không qua FastMCP, vd script/test) coi là client nội bộ cục bộ;
streamable-http LUÔN bắt buộc API key hợp lệ, không có ngoại lệ.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from mcp.server.fastmcp import Context, FastMCP

from hpu_library_mcp.config import get_settings
from hpu_library_mcp.db import Database
from hpu_library_mcp.errors import McpToolError, RateLimitedError, to_error_response
from hpu_library_mcp.logging_setup import configure_logging, current_allowed_levels, get_logger, tool_call_context
from hpu_library_mcp.models import NodeList
from hpu_library_mcp.providers.dspace.provider import DSpaceProvider
from hpu_library_mcp.providers.registry import ProviderRegistry
from hpu_library_mcp.security.keys import SCOPE_ALLOWED_LEVELS, ApiKeyStore, PostgresApiKeyStore, StaticApiKeyStore
from hpu_library_mcp.security.rate_limit import RateLimiter
from hpu_library_mcp.security.resolve import STDIO_LOCAL_KEY_ID, STDIO_LOCAL_SCOPE, ResolvedIdentity, resolve_identity
from hpu_library_mcp.vector.gemini_embedding import GeminiEmbeddingProvider
from hpu_library_mcp.vector.store import VectorStore

logger = get_logger(__name__)

mcp = FastMCP("hpu-library-mcp")

_registry: ProviderRegistry | None = None
_database: Database | None = None
_key_store: ApiKeyStore | None = None
_key_store_resolved = False
_rate_limiter = RateLimiter()


def get_database() -> Database | None:
    """1 Database dùng chung cho VectorStore (Sprint 3) + PostgresApiKeyStore (Sprint 4)."""
    global _database
    settings = get_settings()
    if not settings.database_url:
        return None
    if _database is None:
        _database = Database(settings.database_url)
    return _database


def get_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        settings = get_settings()
        database = get_database()
        embedding_provider = None
        vector_store = None
        has_gemini_key = bool(settings.gemini_api_key.get_secret_value())
        if has_gemini_key and database is not None:
            embedding_provider = GeminiEmbeddingProvider(
                api_key=settings.gemini_api_key.get_secret_value(),
                model=settings.gemini_embedding_model,
                dimensions=settings.gemini_embedding_dimensions,
                batch_size=settings.gemini_embedding_batch_size,
                timeout=settings.gemini_http_timeout_seconds,
            )
            vector_store = VectorStore(database)
        elif has_gemini_key or database is not None:
            logger.warning("semantic_search_partially_configured - can ca GEMINI_API_KEY va DATABASE_URL")
        registry = ProviderRegistry()
        registry.register(
            DSpaceProvider(settings=settings, embedding_provider=embedding_provider, vector_store=vector_store)
        )
        _registry = registry
    return _registry


def get_key_store() -> ApiKeyStore | None:
    """PostgresApiKeyStore nếu có DATABASE_URL, else StaticApiKeyStore (dev) nếu có
    DEV_STATIC_API_KEY, else None (mọi request streamable-http có key đều bị từ chối)."""
    global _key_store, _key_store_resolved
    if not _key_store_resolved:
        settings = get_settings()
        database = get_database()
        if database is not None:
            _key_store = PostgresApiKeyStore(database)
        elif settings.dev_static_api_key.get_secret_value():
            _key_store = StaticApiKeyStore(
                raw_key=settings.dev_static_api_key.get_secret_value(),
                scope=settings.dev_static_api_key_scope,
                rate_limit=settings.rate_limit_default_per_minute,
            )
        _key_store_resolved = True
    return _key_store


_STDIO_LOCAL_IDENTITY = ResolvedIdentity(
    key_id=STDIO_LOCAL_KEY_ID,
    scope=STDIO_LOCAL_SCOPE,
    allowed_levels=SCOPE_ALLOWED_LEVELS[STDIO_LOCAL_SCOPE],
    rate_limit=None,
)


F = TypeVar("F", bound=Callable[..., Awaitable[dict[str, Any]]])


def _handle_errors(tool_name: str) -> Callable[[F], F]:
    """Bọc mỗi tool: resolve identity + rate limit + gắn log + chặn exception rò rỉ.

    Xem 03-tools-spec.md ("Lỗi trả cấu trúc {error:{code,message}}, không lộ chi tiết").
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            ctx = kwargs.get("ctx")
            try:
                # ctx=None: gọi trực tiếp không qua FastMCP (script nội bộ, test) -> coi
                # như client nội bộ cục bộ, cùng quy tắc với stdio (xem security/resolve.py).
                identity = _STDIO_LOCAL_IDENTITY if ctx is None else await resolve_identity(
                    ctx, key_store=get_key_store()
                )
            except McpToolError as exc:
                return exc.to_response()

            with tool_call_context(
                tool_name, key_id=identity.key_id, scope=identity.scope, allowed_levels=identity.allowed_levels
            ):
                effective_limit = identity.rate_limit
                if effective_limit is None and identity.key_id != STDIO_LOCAL_KEY_ID:
                    effective_limit = get_settings().rate_limit_default_per_minute
                if effective_limit is not None and not _rate_limiter.allow(
                    identity.key_id, limit_per_window=effective_limit
                ):
                    logger.warning("rate_limited")
                    return RateLimitedError().to_response()

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
async def get_item(id: str, source: str = "dspace", ctx: Context | None = None) -> dict[str, Any]:
    """Lấy metadata Dublin Core chuẩn hóa + danh sách bitstream của 1 tài liệu thư viện."""
    provider = get_registry().get(source)
    resource = await provider.get(id, allowed_levels=current_allowed_levels())
    return resource.model_dump(mode="json")


@mcp.tool()
@_handle_errors("list_communities")
async def list_communities(
    parent: str | None = None, source: str = "dspace", ctx: Context | None = None
) -> dict[str, Any]:
    """Liệt kê cây đơn vị (communities) của thư viện. Không truyền parent -> danh sách gốc."""
    provider = get_registry().get(source)
    nodes = await provider.list_communities(parent=parent, allowed_levels=current_allowed_levels())
    return NodeList(nodes=nodes).model_dump(mode="json")


@mcp.tool()
@_handle_errors("list_collections")
async def list_collections(
    parent: str | None = None, source: str = "dspace", ctx: Context | None = None
) -> dict[str, Any]:
    """Liệt kê bộ sưu tập (collections). Truyền parent = id community để lọc theo đơn vị."""
    provider = get_registry().get(source)
    nodes = await provider.list_collections(parent=parent, allowed_levels=current_allowed_levels())
    return NodeList(nodes=nodes).model_dump(mode="json")


@mcp.tool()
@_handle_errors("get_recent_items")
async def get_recent_items(
    collection: str | None = None, limit: int = 10, source: str = "dspace", ctx: Context | None = None
) -> dict[str, Any]:
    """Lấy danh sách tài liệu mới nạp gần đây, sắp xếp giảm dần theo ngày nạp."""
    provider = get_registry().get(source)
    resources = await provider.get_recent_items(
        collection=collection, limit=limit, allowed_levels=current_allowed_levels()
    )
    return {"items": [r.model_dump(mode="json") for r in resources]}


@mcp.tool()
@_handle_errors("get_bitstream_link")
async def get_bitstream_link(
    item_id: str, bitstream_id: str, source: str = "dspace", ctx: Context | None = None
) -> dict[str, Any]:
    """Lấy link tải 1 tệp (bitstream) cụ thể của tài liệu, kèm mức truy cập yêu cầu."""
    provider = get_registry().get(source)
    link = await provider.get_bitstream_link(item_id, bitstream_id, allowed_levels=current_allowed_levels())
    return link.model_dump(mode="json")


@mcp.tool()
@_handle_errors("search_library")
async def search_library(
    query: str,
    source: str = "dspace",
    scope: str = "metadata",
    filters: dict[str, Any] | None = None,
    facets: list[str] | None = None,
    page: int = 1,
    page_size: int = 10,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Tìm theo từ khóa (metadata và/hoặc nội dung), có filter/facet/phân trang/highlight.

    scope: "metadata" | "fulltext" | "both". filters có thể gồm collection, community,
    year_from, year_to, type, author. facets: danh sách trong ["type","year","author"].
    """
    provider = get_registry().get(source)
    result = await provider.search(
        query,
        filters=filters,
        scope=scope,
        facets=facets,
        page=page,
        page_size=page_size,
        allowed_levels=current_allowed_levels(),
    )
    return result.model_dump(mode="json")


@mcp.tool()
@_handle_errors("library_stats")
async def library_stats(
    source: str = "dspace", group_by: list[str] | None = None, ctx: Context | None = None
) -> dict[str, Any]:
    """Thống kê số lượng tài liệu theo type/year/collection (qua facet Solr)."""
    provider = get_registry().get(source)
    stats = await provider.stats(group_by=group_by, allowed_levels=current_allowed_levels())
    return stats.model_dump(mode="json")


@mcp.tool()
@_handle_errors("semantic_search_documents")
async def semantic_search_documents(
    query: str,
    source: str = "dspace",
    k: int = 8,
    filters: dict[str, Any] | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Tìm theo Ý NGHĨA trên các đoạn tài liệu đã embed (Tầng 3), trả kèm trích dẫn nguồn."""
    provider = get_registry().get(source)
    chunks = await provider.semantic_search(query, k=k, filters=filters, allowed_levels=current_allowed_levels())
    return {
        "chunks": [c.model_dump(mode="json") for c in chunks],
        "citations": [{"id": c.item_id, "url": c.url, "page": c.page} for c in chunks],
    }


@mcp.tool()
@_handle_errors("get_document_text")
async def get_document_text(
    id: str, query: str | None = None, page: int | None = None, source: str = "dspace", ctx: Context | None = None
) -> dict[str, Any]:
    """Bóc & trả nội dung tài liệu (Tầng 2, PDF). Có xác thực — tôn trọng phân quyền."""
    provider = get_registry().get(source)
    doc = await provider.get_text(id, query=query, page=page, allowed_levels=current_allowed_levels())
    return doc.model_dump(mode="json")


@mcp.tool()
@_handle_errors("find_in_document")
async def find_in_document(
    id: str, query: str, page: int | None = None, source: str = "dspace", ctx: Context | None = None
) -> dict[str, Any]:
    """Tìm các đoạn khớp `query` trong 1 tài liệu cụ thể (Tầng 2). Có xác thực."""
    provider = get_registry().get(source)
    doc = await provider.get_text(id, query=query, page=page, allowed_levels=current_allowed_levels())
    return doc.model_dump(mode="json")


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
