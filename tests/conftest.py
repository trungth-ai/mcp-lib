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


@pytest.fixture
def sample_item() -> dict[str, Any]:
    import copy

    return copy.deepcopy(SAMPLE_ITEM)
