from __future__ import annotations

from typing import Any

import pytest

SAMPLE_ITEM: dict[str, Any] = {
    "uuid": "item-uuid-1",
    "handle": "123456789/42",
    "name": "Ứng dụng học máy trong dự báo tuyển sinh",
    "metadata": [
        {"key": "dc.title", "value": "Ứng dụng học máy trong dự báo tuyển sinh", "language": None},
        {"key": "dc.contributor.author", "value": "Nguyễn Văn A", "language": None},
        {"key": "dc.contributor.author", "value": "Trần Thị B", "language": None},
        {"key": "dc.date.issued", "value": "2023-05-01", "language": None},
        {"key": "dc.date.accessioned", "value": "2023-06-01T00:00:00Z", "language": None},
        {"key": "dc.type", "value": "Thesis", "language": None},
        {"key": "dc.language.iso", "value": "vi", "language": None},
        {"key": "dc.description.abstract", "value": "Luận văn nghiên cứu ứng dụng học máy...", "language": None},
    ],
    "parentCollection": {"uuid": "col-1", "name": "Luận văn Thạc sĩ"},
    "parentCommunityList": [{"uuid": "comm-1", "name": "Khoa CNTT"}],
    "bitstreams": [
        {
            "uuid": "bit-1",
            "name": "toanvan.pdf",
            "bundleName": "ORIGINAL",
            "mimeType": "application/pdf",
            "sizeBytes": 2451234,
            "retrieveLink": "/bitstreams/bit-1/retrieve",
        },
        {
            "uuid": "bit-license",
            "name": "license.txt",
            "bundleName": "LICENSE",
            "mimeType": "text/plain",
            "sizeBytes": 100,
            "retrieveLink": "/bitstreams/bit-license/retrieve",
        },
    ],
}

ANON_READ_POLICY = [{"action": "READ", "groupId": 0}]
INTERNAL_READ_POLICY = [{"action": "READ", "groupId": 5}]
NO_READ_POLICY: list[dict[str, Any]] = []
FUTURE_EMBARGO_POLICY = [{"action": "READ", "groupId": 0, "startDate": "2999-01-01"}]
EXPIRED_POLICY = [{"action": "READ", "groupId": 0, "endDate": "2000-01-01"}]


class FakeDSpaceRestClient:
    """Thay thế DSpaceRestClient thật cho test provider — không gọi HTTP."""

    def __init__(self, routes: dict[str, Any]) -> None:
        self._routes = routes
        self.calls: list[str] = []

    async def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        self.calls.append(path)
        if path not in self._routes:
            raise AssertionError(f"FakeDSpaceRestClient: route chưa mock cho {path}")
        value = self._routes[path]
        if isinstance(value, Exception):
            raise value
        return value

    async def aclose(self) -> None:
        pass


class FakeSolrClient:
    """Thay thế SolrClient thật cho test provider — không gọi HTTP.

    `responses` là 1 raw response (dùng cho mọi lần gọi) hoặc list các response/exception
    trả tuần tự theo từng lần select() (dùng để test retry/suy biến).
    """

    def __init__(self, responses: Any) -> None:
        self._responses = responses if isinstance(responses, list) else [responses]
        self.calls: list[list[tuple[str, Any]]] = []

    async def select(self, params: list[tuple[str, Any]]) -> Any:
        self.calls.append(params)
        index = min(len(self.calls) - 1, len(self._responses) - 1)
        value = self._responses[index]
        if isinstance(value, Exception):
            raise value
        return value

    async def aclose(self) -> None:
        pass


def solr_params_dict(params: list[tuple[str, Any]]) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for key, value in params:
        out.setdefault(key, []).append(value)
    return out


@pytest.fixture
def sample_item() -> dict[str, Any]:
    import copy

    return copy.deepcopy(SAMPLE_ITEM)
