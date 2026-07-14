"""HTTP client mỏng gọi DSpace 7.x REST (/server/api) — HAL/HATEOAS.

Chỉ gửi GET (read-only) + follow redirect (dùng cho /pid/find?id=<handle> -> item), retry 1
lần khi 401 (relogin nếu có service account), không lộ chi tiết lỗi. Mọi read mặc định
chạy ẩn danh (HPU chưa cấp service account) — khi CÓ credentials thì tự đính JWT.

Tham số `anonymous=True` ép bỏ JWT cho 1 request cụ thể — dùng cho library_stats khi key
`partner` chỉ được thấy public: gọi Discovery ẩn danh để DSpace tự lọc theo quyền đọc
Anonymous (thay cho cơ chế `fq=read:g0` của Solr 6.x — xem docs/DECISIONS.md).
"""

from __future__ import annotations

from typing import Any

import httpx

from hpu_library_mcp.errors import NotFoundError, UpstreamError
from hpu_library_mcp.logging_setup import get_logger
from hpu_library_mcp.providers.dspace.auth_v7 import DSpace7Auth

logger = get_logger(__name__)


class DSpace7Client:
    def __init__(
        self,
        *,
        base_url: str,
        timeout: float = 10.0,
        service_email: str = "",
        service_password: str = "",
    ) -> None:
        # follow_redirects: /pid/find?id=<handle> trả 302 -> /core/items/<uuid>.
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout, follow_redirects=True
        )
        self.auth = DSpace7Auth(self._http, service_email, service_password)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | list[tuple[str, Any]] | None = None,
        anonymous: bool = False,
    ) -> Any:
        response = await self._request("GET", path, params=params, anonymous=anonymous)
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            logger.warning("dspace7_response_not_json path=%s", path)
            raise UpstreamError() from exc

    async def get_bytes(self, url: str, *, anonymous: bool = False) -> bytes:
        """Tải nội dung thô (bitstream/PDF). `url` thường là link content tuyệt đối
        (_links.content.href) — httpx dùng nguyên URL đó, bỏ qua base_url."""
        response = await self._request("GET", url, anonymous=anonymous)
        return response.content

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | list[tuple[str, Any]] | None = None,
        anonymous: bool = False,
        _retry_on_auth: bool = True,
    ) -> httpx.Response:
        headers = {} if anonymous else await self.auth.auth_headers()
        try:
            response = await self._http.request(method, path, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            logger.warning("dspace7_request_timeout path=%s", path)
            raise UpstreamError() from exc
        except httpx.HTTPError as exc:
            logger.warning("dspace7_request_network_error path=%s", path)
            raise UpstreamError() from exc

        # Chỉ thử relogin khi có credentials và request này không cố tình ẩn danh.
        if (
            response.status_code == 401
            and _retry_on_auth
            and not anonymous
            and self.auth.has_credentials
        ):
            await self.auth.get_token(force_refresh=True)
            return await self._request(
                method, path, params=params, anonymous=anonymous, _retry_on_auth=False
            )

        if response.status_code == 404:
            raise NotFoundError("Không tìm thấy tài nguyên trong hệ thống thư viện.")

        if response.status_code >= 400:
            logger.warning("dspace7_request_failed path=%s status=%s", path, response.status_code)
            raise UpstreamError()

        return response
