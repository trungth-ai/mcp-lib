"""Test DSpace7Client + DSpace7Auth (client_v7.py, auth_v7.py) qua respx (mock HTTP).

Xác minh: đọc ẩn danh không đính JWT; có service account thì đi đúng luồng CSRF -> login
(JWT trong header Authorization) -> đính Bearer; retry 1 lần khi 401; lỗi không lộ chi tiết.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from hpu_library_mcp.errors import NotFoundError, UpstreamError
from hpu_library_mcp.providers.dspace.client_v7 import DSpace7Client

BASE = "https://lib.hpu.edu.vn/server/api"


@respx.mock
async def test_get_json_success_anonymous_sends_no_bearer():
    route = respx.get(f"{BASE}/core/items/x").mock(return_value=httpx.Response(200, json={"uuid": "x"}))
    client = DSpace7Client(base_url=BASE)  # không có service account -> ẩn danh
    try:
        result = await client.get_json("/core/items/x")
    finally:
        await client.aclose()
    assert result == {"uuid": "x"}
    assert "Authorization" not in route.calls.last.request.headers


@respx.mock
async def test_get_json_404_raises_not_found():
    respx.get(f"{BASE}/core/items/missing").mock(return_value=httpx.Response(404))
    client = DSpace7Client(base_url=BASE)
    try:
        with pytest.raises(NotFoundError):
            await client.get_json("/core/items/missing")
    finally:
        await client.aclose()


@respx.mock
async def test_get_json_server_error_and_timeout_raise_upstream():
    respx.get(f"{BASE}/a").mock(return_value=httpx.Response(500))
    respx.get(f"{BASE}/b").mock(side_effect=httpx.TimeoutException("t"))
    client = DSpace7Client(base_url=BASE)
    try:
        with pytest.raises(UpstreamError):
            await client.get_json("/a")
        with pytest.raises(UpstreamError):
            await client.get_json("/b")
    finally:
        await client.aclose()


@respx.mock
async def test_service_account_does_csrf_then_login_then_attaches_bearer():
    csrf = respx.get(f"{BASE}/security/csrf").mock(
        return_value=httpx.Response(204, headers={"DSPACE-XSRF-TOKEN": "csrf-tok"})
    )
    login = respx.post(f"{BASE}/authn/login").mock(
        return_value=httpx.Response(200, headers={"Authorization": "Bearer jwt-xyz"})
    )
    target = respx.get(f"{BASE}/core/items/x").mock(return_value=httpx.Response(200, json={"uuid": "x"}))

    client = DSpace7Client(base_url=BASE, service_email="svc@hpu.edu.vn", service_password="secret")
    try:
        await client.get_json("/core/items/x")
    finally:
        await client.aclose()

    assert csrf.called and login.called
    # CSRF token phải được gửi lại ở header X-XSRF-TOKEN khi POST login
    assert login.calls.last.request.headers.get("X-XSRF-TOKEN") == "csrf-tok"
    assert target.calls.last.request.headers.get("Authorization") == "Bearer jwt-xyz"


@respx.mock
async def test_401_triggers_relogin_and_retries_once():
    respx.get(f"{BASE}/security/csrf").mock(
        return_value=httpx.Response(204, headers={"DSPACE-XSRF-TOKEN": "c"})
    )
    login = respx.post(f"{BASE}/authn/login").mock(
        return_value=httpx.Response(200, headers={"Authorization": "Bearer new-jwt"})
    )
    target = respx.get(f"{BASE}/core/items/x").mock(
        side_effect=[httpx.Response(401), httpx.Response(200, json={"uuid": "x"})]
    )
    client = DSpace7Client(base_url=BASE, service_email="svc@hpu.edu.vn", service_password="s")
    try:
        result = await client.get_json("/core/items/x")
    finally:
        await client.aclose()
    assert result == {"uuid": "x"}
    assert login.call_count == 2  # login ban đầu + relogin sau 401
    assert target.call_count == 2


@respx.mock
async def test_login_failure_raises_upstream_without_leaking_password():
    respx.get(f"{BASE}/security/csrf").mock(
        return_value=httpx.Response(204, headers={"DSPACE-XSRF-TOKEN": "c"})
    )
    respx.post(f"{BASE}/authn/login").mock(return_value=httpx.Response(401))
    client = DSpace7Client(base_url=BASE, service_email="svc@hpu.edu.vn", service_password="topsecret")
    try:
        with pytest.raises(UpstreamError) as exc_info:
            await client.get_json("/core/items/x")
    finally:
        await client.aclose()
    assert "topsecret" not in str(exc_info.value)


@respx.mock
async def test_anonymous_flag_skips_bearer_even_with_credentials():
    respx.get(f"{BASE}/security/csrf").mock(
        return_value=httpx.Response(204, headers={"DSPACE-XSRF-TOKEN": "c"})
    )
    respx.post(f"{BASE}/authn/login").mock(
        return_value=httpx.Response(200, headers={"Authorization": "Bearer jwt"})
    )
    route = respx.get(f"{BASE}/discover/search/objects").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    client = DSpace7Client(base_url=BASE, service_email="svc@hpu.edu.vn", service_password="s")
    try:
        await client.get_json("/discover/search/objects", anonymous=True)
    finally:
        await client.aclose()
    # anonymous=True: không đăng nhập, không đính Bearer (dùng cho library_stats partner)
    assert "Authorization" not in route.calls.last.request.headers
