"""HTTP client mỏng gọi Solr Discovery core của DSpace — xem 02-architecture.md §5.

Chỉ chịu trách nhiệm gửi request/parse JSON thô; xây query + diễn giải kết quả nằm ở
provider.py (tách để dễ test độc lập).
"""

from __future__ import annotations

from typing import Any

import httpx

from hpu_library_mcp.errors import SolrBadRequestError, UpstreamError
from hpu_library_mcp.logging_setup import get_logger

logger = get_logger(__name__)


class SolrClient:
    def __init__(self, *, base_url: str, core: str, timeout: float = 10.0) -> None:
        self._http = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)
        self._core = core

    async def aclose(self) -> None:
        await self._http.aclose()

    async def select(self, params: list[tuple[str, Any]]) -> dict[str, Any]:
        """GET {base_url}/{core}/select. params là list (key, value) — cho phép lặp key
        (fq, facet.field...). Ném SolrBadRequestError khi 400 (thường do sai tên field —
        caller có thể suy biến), UpstreamError khi lỗi mạng/5xx/timeout/JSON hỏng.
        """
        query = [*params, ("wt", "json")]
        try:
            response = await self._http.get(f"/{self._core}/select", params=query)
        except httpx.TimeoutException as exc:
            logger.warning("solr_request_timeout core=%s", self._core)
            raise UpstreamError("Không thể tìm kiếm trong hệ thống thư viện lúc này.") from exc
        except httpx.HTTPError as exc:
            logger.warning("solr_request_network_error core=%s", self._core)
            raise UpstreamError("Không thể tìm kiếm trong hệ thống thư viện lúc này.") from exc

        if response.status_code == 400:
            logger.warning("solr_bad_request core=%s", self._core)
            raise SolrBadRequestError("Yêu cầu tìm kiếm không hợp lệ.")

        if response.status_code >= 400:
            logger.warning("solr_request_failed core=%s status=%s", self._core, response.status_code)
            raise UpstreamError("Không thể tìm kiếm trong hệ thống thư viện lúc này.")

        try:
            return response.json()
        except ValueError as exc:
            logger.warning("solr_response_not_json core=%s", self._core)
            raise UpstreamError("Không thể tìm kiếm trong hệ thống thư viện lúc này.") from exc
