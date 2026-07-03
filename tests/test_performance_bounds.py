"""Proxy cho NFR-3 (hiệu năng) — 06-test-plan.md §2.5.

KHÔNG đo được p95 thật (cần DSpace/Solr/mạng LAN thật, máy dev này không có — xem
docs/PLAN.md). Thay vào đó verify 2 thuộc tính kiến trúc quyết định hiệu năng thực tế:
1. Số lượt gọi REST/Solr bị CHẶN TRÊN theo tham số client truyền (không phải theo dữ
   liệu nội bộ lớn hơn) — vd get_recent_items không gọi policy cho toàn bộ tập over-fetch.
2. Các lượt gọi REST độc lập trong 1 trang kết quả chạy SONG SONG (asyncio.gather), không
   tuần tự — đo trực tiếp bằng độ trễ giả lập, phát hiện được nếu ai đó lỡ đổi gather
   thành await tuần tự trong tương lai.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from hpu_library_mcp.config import Settings
from hpu_library_mcp.providers.dspace.provider import DSpaceProvider
from tests.conftest import ANON_READ_POLICY, FakeSolrClient


class DelayedRestClient:
    """Như FakeDSpaceRestClient nhưng có độ trễ giả lập mỗi lần gọi — dùng đo tính song song."""

    def __init__(self, routes: dict[str, Any], *, delay_seconds: float) -> None:
        self._routes = routes
        self._delay = delay_seconds
        self.call_count = 0

    async def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        self.call_count += 1
        await asyncio.sleep(self._delay)
        if path not in self._routes:
            raise AssertionError(f"route chưa mock cho {path}")
        value = self._routes[path]
        if isinstance(value, Exception):
            raise value
        return value

    async def get_bytes(self, path: str, *, params: dict[str, Any] | None = None) -> bytes:
        raise NotImplementedError

    async def aclose(self) -> None:
        pass


def _make_item(idx: int, sample_item: dict) -> dict:
    item = dict(sample_item)
    item["uuid"] = f"item-uuid-{idx}"
    item["handle"] = f"123456789/{idx}"
    item["metadata"] = [{"key": "dc.title", "value": f"Tài liệu {idx}"}]
    return item


async def test_get_recent_items_policy_calls_bounded_by_limit_not_overfetch(sample_item):
    # Over-fetch tối đa 200 item (xem provider._RECENT_ITEMS_OVERFETCH_CAP cũ, nay ở adapter_v6)
    # nhưng chỉ nên gọi policy cho đúng `limit` item sau khi sort, không phải cho cả 200.
    many_items = [_make_item(i, sample_item) for i in range(150)]
    routes = {"/items": many_items}
    for i in range(150):
        routes[f"/items/item-uuid-{i}/policy"] = ANON_READ_POLICY

    client = DelayedRestClient(routes, delay_seconds=0)
    provider = DSpaceProvider(settings=Settings(), client=client)

    await provider.get_recent_items(limit=10)

    # 1 lượt lấy danh sách + tối đa 10 lượt policy (không phải 150)
    assert client.call_count <= 1 + 10


async def test_search_library_issues_exactly_one_solr_call_per_page():
    solr_response = {"response": {"numFound": 0, "docs": []}, "facet_counts": {"facet_fields": {}}}
    client = DelayedRestClient({}, delay_seconds=0)
    solr = FakeSolrClient(solr_response)
    provider = DSpaceProvider(settings=Settings(), client=client, solr_client=solr)

    await provider.search("tuyển sinh", page_size=50)

    assert len(solr.calls) == 1  # không lặp gọi Solr nhiều lần cho 1 trang


async def test_search_library_rest_lookups_bounded_by_page_size(sample_item):
    hits = [f"123456789/{i}" for i in range(10)]
    solr_response = {
        "response": {"numFound": 10, "docs": [{"handle": h} for h in hits]},
        "facet_counts": {"facet_fields": {}},
    }
    routes = {}
    for i in range(10):
        item = dict(sample_item)
        item["uuid"] = f"item-uuid-{i}"
        item["handle"] = f"123456789/{i}"
        routes[f"/handle/123456789/{i}"] = item
        routes[f"/items/item-uuid-{i}/policy"] = ANON_READ_POLICY

    client = DelayedRestClient(routes, delay_seconds=0)
    solr = FakeSolrClient(solr_response)
    provider = DSpaceProvider(settings=Settings(), client=client, solr_client=solr)

    await provider.search("x", page_size=10)

    # Mỗi kết quả tốn đúng 2 lượt REST (resolve + policy) -> chặn trên = 2 * page_size,
    # không phát sinh N+1 ngoài dự kiến (vd gọi lại policy nhiều lần cho cùng 1 item).
    assert client.call_count <= 2 * 10


async def test_search_library_fetches_results_concurrently_not_sequentially(sample_item):
    """Nếu ai đó lỡ đổi asyncio.gather thành vòng lặp await tuần tự trong search(), test
    này sẽ đỏ (thời gian chạy tăng tuyến tính theo số kết quả thay vì gần như không đổi)."""
    delay = 0.05
    hits = [f"123456789/{i}" for i in range(8)]
    solr_response = {
        "response": {"numFound": 8, "docs": [{"handle": h} for h in hits]},
        "facet_counts": {"facet_fields": {}},
    }
    routes = {}
    for i in range(8):
        item = dict(sample_item)
        item["uuid"] = f"item-uuid-{i}"
        item["handle"] = f"123456789/{i}"
        routes[f"/handle/123456789/{i}"] = item
        routes[f"/items/item-uuid-{i}/policy"] = ANON_READ_POLICY

    client = DelayedRestClient(routes, delay_seconds=delay)
    solr = FakeSolrClient(solr_response)
    provider = DSpaceProvider(settings=Settings(), client=client, solr_client=solr)

    started_at = time.monotonic()
    result = await provider.search("x", page_size=8)
    elapsed = time.monotonic() - started_at

    assert len(result.results) == 8
    # Tuần tự sẽ mất ~8 * 2 * delay = 0.8s; song song chỉ mất ~2 * delay = 0.1s (resolve +
    # policy nối tiếp nhau CHO 1 item, nhưng 8 item chạy đồng thời). Cho biên độ rộng rãi
    # (< 5 * delay) để tránh test không ổn định (flaky) trên máy chậm.
    assert elapsed < delay * 5, f"search() có vẻ đang chạy tuần tự, mất {elapsed:.3f}s"
