"""MCP contract — 06-test-plan.md §2.2: "liệt kê tool, JSON schema I/O khớp
03-tools-spec.md; transport stdio & Streamable HTTP đều gọi được."

Trước bản fix này, việc khớp schema chỉ được xác nhận thủ công qua bash một lần, không
nằm trong bộ pytest — commit sau có thể đổi tên/param tool mà không ai biết cho tới khi
client thật gãy.
"""

from __future__ import annotations

from starlette.testclient import TestClient

from hpu_library_mcp.server import mcp

EXPECTED_TOOLS = {
    "get_item": {"id", "source"},
    "list_communities": {"parent", "source"},
    "list_collections": {"parent", "source"},
    "get_recent_items": {"collection", "limit", "source"},
    "get_bitstream_link": {"item_id", "bitstream_id", "source"},
    "search_library": {"query", "source", "scope", "filters", "facets", "page", "page_size"},
    "library_stats": {"source", "group_by"},
    "semantic_search_documents": {"query", "source", "k", "filters"},
    "get_document_text": {"id", "query", "page", "source"},
    "find_in_document": {"id", "query", "page", "source"},
}

EXPECTED_REQUIRED = {
    "get_item": {"id"},
    "list_communities": set(),
    "list_collections": set(),
    "get_recent_items": set(),
    "get_bitstream_link": {"item_id", "bitstream_id"},
    "search_library": {"query"},
    "library_stats": set(),
    "semantic_search_documents": {"query"},
    "get_document_text": {"id"},
    "find_in_document": {"id", "query"},
}


async def test_exactly_the_10_documented_tools_are_registered():
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert names == set(EXPECTED_TOOLS)


async def test_tool_schemas_match_spec_params_and_hide_ctx():
    tools = {t.name: t for t in await mcp.list_tools()}
    for name, expected_params in EXPECTED_TOOLS.items():
        schema = tools[name].inputSchema
        actual_params = set(schema.get("properties", {}))
        assert actual_params == expected_params, f"{name}: {actual_params} != {expected_params}"
        assert "ctx" not in actual_params, f"{name}: ctx không được lộ ra schema cho LLM client"


async def test_tool_schemas_required_fields_match_spec():
    tools = {t.name: t for t in await mcp.list_tools()}
    for name, expected_required in EXPECTED_REQUIRED.items():
        actual_required = set(tools[name].inputSchema.get("required", []))
        assert actual_required == expected_required, f"{name}: {actual_required} != {expected_required}"


async def test_every_tool_has_a_docstring_description():
    tools = await mcp.list_tools()
    for tool in tools:
        assert tool.description and len(tool.description) > 10


def test_streamable_http_app_serves_health_without_key():
    app = mcp.streamable_http_app()
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code in (200, 503)
    body = response.json()
    assert "status" in body and "dspace" in body


def test_streamable_http_app_mounts_mcp_endpoint():
    app = mcp.streamable_http_app()
    paths = {getattr(route, "path", None) for route in app.routes}
    assert mcp.settings.streamable_http_path in paths
