"""Đăng nhập service account DSpace REST 6.x (POST /rest/login) — xem 02-architecture.md §4.2.

Token giữ trong bộ nhớ tiến trình, tự refresh khi 401, KHÔNG BAO GIỜ ghi ra log
(NFR-2 / 05-security.md §5).
"""

from __future__ import annotations

import asyncio

import httpx

from hpu_library_mcp.errors import UpstreamError
from hpu_library_mcp.logging_setup import get_logger

logger = get_logger(__name__)


class DSpaceAuth:
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
            return None  # chạy ở chế độ anonymous (chỉ đọc public)
        if self._token and not force_refresh:
            return self._token
        async with self._lock:
            if self._token and not force_refresh:
                return self._token
            await self._login()
        return self._token

    async def auth_headers(self) -> dict[str, str]:
        token = await self.get_token()
        return {"rest-dspace-token": token} if token else {}

    async def _login(self) -> None:
        try:
            response = await self._client.post(
                "/login", data={"email": self._email, "password": self._password}
            )
        except httpx.HTTPError as exc:
            logger.warning("dspace_login_network_error")
            raise UpstreamError("Không đăng nhập được vào hệ thống thư viện.") from exc

        if response.status_code >= 400:
            logger.warning("dspace_login_rejected status=%s", response.status_code)
            raise UpstreamError("Không đăng nhập được vào hệ thống thư viện (service account bị từ chối).")

        token = response.text.strip().strip('"')
        if not token:
            logger.warning("dspace_login_empty_token")
            raise UpstreamError("Không đăng nhập được vào hệ thống thư viện.")
        self._token = token
