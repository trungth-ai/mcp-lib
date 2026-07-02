"""HTTP client mỏng gọi DSpace REST 6.x — retry 1 lần khi 401, không lộ chi tiết lỗi."""

from __future__ import annotations

from typing import Any

import httpx

from hpu_library_mcp.errors import NotFoundError, UpstreamError
from hpu_library_mcp.logging_setup import get_logger
from hpu_library_mcp.providers.dspace.auth import DSpaceAuth

logger = get_logger(__name__)


class DSpaceRestClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout: float = 10.0,
        service_email: str = "",
        service_password: str = "",
    ) -> None:
        self._http = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)
        self.auth = DSpaceAuth(self._http, service_email, service_password)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return await self._request("GET", path, params=params)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        _retry_on_auth: bool = True,
    ) -> Any:
        headers = await self.auth.auth_headers()
        try:
            response = await self._http.request(method, path, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            logger.warning("dspace_request_timeout path=%s", path)
            raise UpstreamError() from exc
        except httpx.HTTPError as exc:
            logger.warning("dspace_request_network_error path=%s", path)
            raise UpstreamError() from exc

        if response.status_code == 401 and _retry_on_auth:
            await self.auth.get_token(force_refresh=True)
            return await self._request(method, path, params=params, _retry_on_auth=False)

        if response.status_code == 404:
            raise NotFoundError("Không tìm thấy tài nguyên trong hệ thống thư viện.")

        if response.status_code >= 400:
            logger.warning("dspace_request_failed path=%s status=%s", path, response.status_code)
            raise UpstreamError()

        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            logger.warning("dspace_response_not_json path=%s", path)
            raise UpstreamError() from exc
