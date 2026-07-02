from __future__ import annotations

import httpx
import pytest
import respx

from hpu_library_mcp.errors import NotFoundError, UpstreamError
from hpu_library_mcp.providers.dspace.client import DSpaceRestClient

BASE = "http://10.1.0.205:8088/rest"


@respx.mock
async def test_get_json_success():
    respx.get(f"{BASE}/status").mock(return_value=httpx.Response(200, json={"ok": True}))
    client = DSpaceRestClient(base_url=BASE)
    try:
        result = await client.get_json("/status")
    finally:
        await client.aclose()
    assert result == {"ok": True}


@respx.mock
async def test_get_json_404_raises_not_found():
    respx.get(f"{BASE}/items/missing").mock(return_value=httpx.Response(404))
    client = DSpaceRestClient(base_url=BASE)
    try:
        with pytest.raises(NotFoundError):
            await client.get_json("/items/missing")
    finally:
        await client.aclose()


@respx.mock
async def test_get_json_server_error_raises_upstream_error():
    respx.get(f"{BASE}/items/x").mock(return_value=httpx.Response(500))
    client = DSpaceRestClient(base_url=BASE)
    try:
        with pytest.raises(UpstreamError):
            await client.get_json("/items/x")
    finally:
        await client.aclose()


@respx.mock
async def test_get_json_timeout_raises_upstream_error():
    respx.get(f"{BASE}/items/slow").mock(side_effect=httpx.TimeoutException("timeout"))
    client = DSpaceRestClient(base_url=BASE)
    try:
        with pytest.raises(UpstreamError):
            await client.get_json("/items/slow")
    finally:
        await client.aclose()


@respx.mock
async def test_get_json_401_triggers_relogin_and_retries_once():
    login_route = respx.post(f"{BASE}/login").mock(return_value=httpx.Response(200, text="tok-123"))
    item_route = respx.get(f"{BASE}/items/x").mock(
        side_effect=[httpx.Response(401), httpx.Response(200, json={"uuid": "x"})]
    )
    client = DSpaceRestClient(base_url=BASE, service_email="svc@hpu.edu.vn", service_password="secret")
    try:
        result = await client.get_json("/items/x")
    finally:
        await client.aclose()
    assert result == {"uuid": "x"}
    assert login_route.call_count == 2  # login ban đầu + relogin sau 401
    assert item_route.call_count == 2


@respx.mock
async def test_login_failure_raises_upstream_error_without_leaking_detail():
    respx.post(f"{BASE}/login").mock(return_value=httpx.Response(400))
    client = DSpaceRestClient(base_url=BASE, service_email="svc@hpu.edu.vn", service_password="wrong")
    try:
        with pytest.raises(UpstreamError) as exc_info:
            await client.get_json("/items/x")
    finally:
        await client.aclose()
    assert "wrong" not in str(exc_info.value)


@respx.mock
async def test_anonymous_client_sends_no_auth_header():
    route = respx.get(f"{BASE}/communities/top-communities").mock(return_value=httpx.Response(200, json=[]))
    client = DSpaceRestClient(base_url=BASE)  # không truyền service_email/password
    try:
        await client.get_json("/communities/top-communities")
    finally:
        await client.aclose()
    sent_request = route.calls.last.request
    assert "rest-dspace-token" not in sent_request.headers
