"""Test ánh xạ HAL DSpace 7.x -> schema chuẩn hóa (mapping_v7.py).

Fixture bám hình dạng JSON THẬT quan sát trên https://lib.hpu.edu.vn/server/api
(DSpace 7.6.5, 2026-07-14): metadata dạng dict, bundles/bitstreams/format lồng qua
`_embedded`, mime nằm trong format embed, collection/community qua owningCollection.
"""

from __future__ import annotations

from typing import Any

from hpu_library_mcp.providers.dspace.mapping_v7 import (
    access_level_from_status,
    map_collection_to_node,
    map_community_to_node,
    map_item_to_resource,
)

PUBLIC_BASE = "https://lib.hpu.edu.vn"


def _hal_item() -> dict[str, Any]:
    return {
        "uuid": "item-uuid-1",
        "handle": "123456789/42",
        "name": "Ứng dụng học máy trong dự báo tuyển sinh",
        "metadata": {
            "dc.title": [{"value": "Ứng dụng học máy trong dự báo tuyển sinh"}],
            "dc.contributor.author": [{"value": "Nguyễn Văn A"}, {"value": "Trần Thị B"}],
            "dc.date.issued": [{"value": "2023-05-01"}],
            "dc.type": [{"value": "Thesis"}],
            "dc.language.iso": [{"value": "vi"}],
            "dc.description.abstract": [{"value": "Luận văn nghiên cứu ứng dụng học máy..."}],
        },
        "_embedded": {
            "owningCollection": {
                "name": "Luận văn Thạc sĩ",
                "_embedded": {"parentCommunity": {"name": "Khoa CNTT"}},
            },
            "bundles": {
                "_embedded": {
                    "bundles": [
                        {
                            "name": "ORIGINAL",
                            "_embedded": {
                                "bitstreams": {
                                    "_embedded": {
                                        "bitstreams": [
                                            {
                                                "uuid": "bit-1",
                                                "name": "toanvan.pdf",
                                                "sizeBytes": 2451234,
                                                "_embedded": {"format": {"mimetype": "application/pdf"}},
                                                "_links": {
                                                    "content": {
                                                        "href": "https://lib.hpu.edu.vn/server/api/core/bitstreams/bit-1/content"
                                                    }
                                                },
                                            }
                                        ]
                                    }
                                }
                            },
                        },
                        {
                            "name": "THUMBNAIL",
                            "_embedded": {
                                "bitstreams": {
                                    "_embedded": {
                                        "bitstreams": [
                                            {
                                                "uuid": "thumb-1",
                                                "name": "toanvan.pdf.jpg",
                                                "_embedded": {"format": {"mimetype": "image/jpeg"}},
                                                "_links": {"content": {"href": "https://x/thumb"}},
                                            }
                                        ]
                                    }
                                }
                            },
                        },
                    ]
                }
            },
        },
    }


def test_map_item_open_access_is_public_with_full_metadata():
    resource = map_item_to_resource(_hal_item(), public_base_url=PUBLIC_BASE, access_status="open.access")
    assert resource.access_level == "public"
    assert resource.title == "Ứng dụng học máy trong dự báo tuyển sinh"
    assert resource.authors == ["Nguyễn Văn A", "Trần Thị B"]
    assert resource.year == 2023
    assert resource.type == "Thesis"
    assert resource.language == "vi"
    assert resource.collection == "Luận văn Thạc sĩ"
    assert resource.community == "Khoa CNTT"
    assert resource.url == "https://lib.hpu.edu.vn/handle/123456789/42"
    assert resource.id == "123456789/42"


def test_map_item_keeps_only_original_bundle_files():
    resource = map_item_to_resource(_hal_item(), public_base_url=PUBLIC_BASE, access_status="open.access")
    assert len(resource.files) == 1
    file = resource.files[0]
    assert file.bitstream_id == "bit-1"
    assert file.mime == "application/pdf"
    assert file.size == 2451234
    assert file.bitstream_link.endswith("/core/bitstreams/bit-1/content")
    assert file.access_level == "public"


def test_map_item_non_open_status_is_restricted_failsafe():
    for status in ("restricted", "embargo", "metadata.only", None, "gì đó lạ"):
        resource = map_item_to_resource(_hal_item(), public_base_url=PUBLIC_BASE, access_status=status)
        assert resource.access_level == "restricted", status
        # bitstream kế thừa access_level của item
        assert resource.files[0].access_level == "restricted"


def test_access_level_from_status_mapping():
    assert access_level_from_status("open.access") == "public"
    assert access_level_from_status("restricted") == "restricted"
    assert access_level_from_status("embargo") == "restricted"
    assert access_level_from_status(None) == "restricted"


def test_map_item_missing_fields_does_not_crash():
    resource = map_item_to_resource(
        {"uuid": "u", "metadata": {}}, public_base_url=PUBLIC_BASE, access_status=None
    )
    assert resource.title == "(không có tiêu đề)"
    assert resource.authors == []
    assert resource.year is None
    assert resource.files == []
    assert resource.id == "u"
    assert resource.url is None


def test_map_community_and_collection_nodes():
    community = map_community_to_node(
        {"uuid": "comm-1", "name": "English resources", "archivedItemsCount": 5}
    )
    assert community.id == "comm-1"
    assert community.type == "community"
    assert community.count == 5

    # archivedItemsCount = -1 (chưa tính) -> count None, không phải -1
    collection = map_collection_to_node(
        {"uuid": "col-1", "name": "Đề cương", "archivedItemsCount": -1}
    )
    assert collection.type == "collection"
    assert collection.count is None
