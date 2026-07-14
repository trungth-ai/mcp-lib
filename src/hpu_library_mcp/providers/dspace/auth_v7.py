"""Đăng nhập service account DSpace 7.x REST (/server/api) — JWT + CSRF.

Khác REST 6.x (POST /rest/login trả token thô trong body), DSpace 7 dùng:
  1. GET  /security/csrf  -> set cookie DSPACE-XSRF-COOKIE + header DSPACE-XSRF-TOKEN
  2. POST /authn/login    -> body form user/password, kèm header X-XSRF-TOKEN;
     token JWT nằm trong HEADER `Authorization: Bearer <jwt>` của response, KHÔNG ở body.
Luồng CSRF đã xác minh thật 2026-07-14 (GET /server/api/security/csrf -> 204 + 2 header
trên). Bước login POST chưa chạy được vì HPU CHƯA cấp service account (mọi read hiện chạy
ẩn danh — xem docs/DECISIONS.md), nhưng bám đúng tài liệu chính thức DSpace 7 REST.

Token giữ trong bộ nhớ tiến trình, tự refresh khi 401, KHÔNG BAO GIỜ ghi ra log
(NFR-2 / 05-security.md §5). Cookie XSRF do chính httpx.AsyncClient (có cookie jar) tự giữ.
"""

from __future__ import annotations

import asyncio

import httpx

from hpu_library_mcp.errors import UpstreamError
from hpu_library_mcp.logging_setup import get_logger

logger = get_logger(__name__)

# Header DSpace trả token CSRF ra + header client phải gửi lại khi POST (mutating request).
_CSRF_RESPONSE_HEADER = "DSPACE-XSRF-TOKEN"
_CSRF_REQUEST_HEADER = "X-XSRF-TOKEN"


class DSpace7Auth:
    def __init__(self, client: httpx.AsyncClient, email: str, password: str) -> None:
        self._client = client
        self._email = email
        self._password = password
        self._token: str | None = None
        self._lock = asyncio.Lock()

    @property
    def has_credentials(self) -> bool:
        return bool(self._email and self._password)

    async def get_token(self, *, force_refresh: bool = False) -> str | None:
        if not self.has_credentials:
            return None  # chạy ở chế độ ẩn danh (chỉ đọc tài liệu public/open.access)
        if self._token and not force_refresh:
            return self._token
        async with self._lock:
            if self._token and not force_refresh:
                return self._token
            await self._login()
        return self._token

    async def auth_headers(self) -> dict[str, str]:
        token = await self.get_token()
        return {"Authorization": f"Bearer {token}"} if token else {}

    async def _fetch_csrf_token(self) -> str | None:
        """Lấy token CSRF + để httpx tự giữ cookie DSPACE-XSRF-COOKIE cho POST kế tiếp."""
        try:
            response = await self._client.get("/security/csrf")
        except httpx.HTTPError as exc:
            logger.warning("dspace7_csrf_fetch_error")
            raise UpstreamError("Không đăng nhập được vào hệ thống thư viện.") from exc
        return response.headers.get(_CSRF_RESPONSE_HEADER)

    async def _login(self) -> None:
        csrf_token = await self._fetch_csrf_token()
        headers = {_CSRF_REQUEST_HEADER: csrf_token} if csrf_token else {}
        try:
            response = await self._client.post(
                "/authn/login",
                data={"user": self._email, "password": self._password},
                headers=headers,
            )
        except httpx.HTTPError as exc:
            logger.warning("dspace7_login_network_error")
            raise UpstreamError("Không đăng nhập được vào hệ thống thư viện.") from exc

        if response.status_code >= 400:
            logger.warning("dspace7_login_rejected status=%s", response.status_code)
            raise UpstreamError("Không đăng nhập được vào hệ thống thư viện (service account bị từ chối).")

        # DSpace 7 trả JWT trong header Authorization, KHÔNG ở body.
        auth_header = response.headers.get("Authorization") or response.headers.get("authorization")
        token = ""
        if auth_header:
            token = auth_header.split(" ", 1)[1].strip() if " " in auth_header else auth_header.strip()
        if not token:
            logger.warning("dspace7_login_empty_token")
            raise UpstreamError("Không đăng nhập được vào hệ thống thư viện.")
        self._token = token
