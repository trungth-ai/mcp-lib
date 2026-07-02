from __future__ import annotations

from hpu_library_mcp.providers.dspace.mapping import (
    infer_access_level,
    map_item_to_resource,
)
from tests.conftest import (
    ANON_READ_POLICY,
    EXPIRED_POLICY,
    FUTURE_EMBARGO_POLICY,
    INTERNAL_READ_POLICY,
    NO_READ_POLICY,
)

REST_BASE = "http://10.1.0.205:8088/rest"
PUBLIC_BASE = "https://lib.hpu.edu.vn"


def test_map_item_to_resource_full(sample_item):
    resource = map_item_to_resource(
        sample_item,
        rest_base_url=REST_BASE,
        public_base_url=PUBLIC_BASE,
        resource_policies=ANON_READ_POLICY,
    )

    assert resource.id == "123456789/42"
    assert resource.title == "Ứng dụng học máy trong dự báo tuyển sinh"
    assert resource.authors == ["Nguyễn Văn A", "Trần Thị B"]
    assert resource.year == 2023
    assert resource.type == "Thesis"
    assert resource.language == "vi"
    assert resource.collection == "Luận văn Thạc sĩ"
    assert resource.community == "Khoa CNTT"
    assert resource.url == "https://lib.hpu.edu.vn/handle/123456789/42"
    assert resource.access_level == "public"


def test_map_item_bitstreams_only_original_bundle(sample_item):
    resource = map_item_to_resource(
        sample_item, rest_base_url=REST_BASE, public_base_url=PUBLIC_BASE, resource_policies=ANON_READ_POLICY
    )
    # bundle LICENSE phải bị loại, chỉ giữ ORIGINAL
    assert len(resource.files) == 1
    assert resource.files[0].name == "toanvan.pdf"
    assert resource.files[0].bitstream_link == f"{REST_BASE}/bitstreams/bit-1/retrieve"
    assert resource.files[0].access_level == "public"


def test_map_item_missing_fields_does_not_crash():
    item = {"uuid": "u1", "handle": "1/1", "metadata": []}
    resource = map_item_to_resource(
        item, rest_base_url=REST_BASE, public_base_url=PUBLIC_BASE, resource_policies=None
    )
    assert resource.title == "(không có tiêu đề)"
    assert resource.authors == []
    assert resource.year is None
    assert resource.files == []
    assert resource.access_level == "restricted"  # mơ hồ -> fail-safe


def test_map_item_no_bitstreams_key():
    item = {"uuid": "u1", "handle": "1/1", "metadata": [{"key": "dc.title", "value": "Không có file"}]}
    resource = map_item_to_resource(
        item, rest_base_url=REST_BASE, public_base_url=PUBLIC_BASE, resource_policies=ANON_READ_POLICY
    )
    assert resource.files == []


def test_map_item_multi_author_and_missing_year(sample_item):
    del sample_item["metadata"][3]  # bỏ dc.date.issued
    resource = map_item_to_resource(
        sample_item, rest_base_url=REST_BASE, public_base_url=PUBLIC_BASE, resource_policies=ANON_READ_POLICY
    )
    assert resource.year is None
    assert len(resource.authors) == 2


# --- access_level inference (05-security.md §4, bất biến bảo mật #2 ở 06-test-plan.md) ---


def test_infer_access_level_anonymous_read_is_public():
    assert infer_access_level(ANON_READ_POLICY) == "public"


def test_infer_access_level_internal_group_is_internal():
    assert infer_access_level(INTERNAL_READ_POLICY) == "internal"


def test_infer_access_level_no_read_policy_is_restricted():
    assert infer_access_level(NO_READ_POLICY) == "restricted"


def test_infer_access_level_none_is_restricted():
    assert infer_access_level(None) == "restricted"


def test_infer_access_level_future_embargo_is_restricted():
    # Anonymous READ nhưng startDate ở tương lai -> chưa mở, không được coi là public.
    assert infer_access_level(FUTURE_EMBARGO_POLICY) == "restricted"


def test_infer_access_level_expired_policy_is_restricted():
    assert infer_access_level(EXPIRED_POLICY) == "restricted"


def test_infer_access_level_mixed_active_anonymous_and_expired_internal_is_public():
    mixed = [
        {"action": "READ", "groupId": 5, "endDate": "2000-01-01"},  # nội bộ nhưng đã hết hạn
        {"action": "READ", "groupId": 0},  # anonymous đang hiệu lực
    ]
    assert infer_access_level(mixed) == "public"
