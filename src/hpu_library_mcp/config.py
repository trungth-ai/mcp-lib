from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Docker secret (Sprint 5, 05-security.md §5): file /run/secrets/<field_name> đè lên field
# cùng tên nếu thư mục tồn tại (chuẩn Docker Swarm/Compose). Chỉ bật khi thư mục thật sự
# có — tránh warning "directory does not exist" khi chạy local/test (không phải Docker).
_SECRETS_DIR = "/run/secrets" if os.path.isdir("/run/secrets") else None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", secrets_dir=_SECRETS_DIR
    )

    # --- DSpace ---
    dspace_version: Literal["6.3", "v10"] = "6.3"
    # Cổng REST xác nhận thật 2026-07-03 (anh Trung kiểm tra trực tiếp trên host DSpace,
    # xem docs/DECISIONS.md) — 8088 trước đây chỉ là GIẢ ĐỊNH sai. Cổng Solr CHƯA xác
    # minh (dùng chung port REST chỉ là phỏng đoán, cần kiểm riêng — xem PLAN.md).
    dspace_rest_base_url: str = "http://10.1.0.205:8081/rest"
    dspace_solr_base_url: str = "http://10.1.0.205:8081/solr"
    # Tên core/field dưới đây là GIẢ ĐỊNH — xác minh ở Sprint 0 (xem 07-sprints.md).
    # Cố tình để cấu hình được thay vì hardcode trong code. Field cấu trúc lõi của
    # DSpace (search.resourcetype, handle) ổn định hơn field metadata (title/author/...)
    # vốn tùy biến theo discovery.xml riêng của từng site — xem docs/DECISIONS.md.
    dspace_solr_search_core: str = "search"
    dspace_solr_fulltext_field: str = "fulltext"
    # Field "catch-all" dùng làm df (default field) khi tìm theo metadata/cả hai.
    dspace_solr_field_default: str = "default"
    dspace_solr_field_handle: str = "handle"
    dspace_solr_field_resourcetype: str = "search.resourcetype"
    dspace_solr_resourcetype_item: str = "2"  # DSpace Constants.ITEM
    dspace_solr_field_collection: str = "location.coll"
    dspace_solr_field_community: str = "location.comm"
    dspace_solr_field_year: str = "dc.date.issued_year"
    dspace_solr_field_type: str = "dc.type_filter"
    dspace_solr_field_author: str = "dc.contributor.author_filter"
    # Field lưu quyền đọc trong Solr (multi-valued, token "g<groupId>"/"e<epersonId>") —
    # cơ chế lõi của DSpace SolrServiceImpl, ổn định hơn field metadata (xem DECISIONS.md).
    # Dùng để lọc library_stats cho key partner (không có REST hậu kiểm từng item như
    # search_library vì stats là facet count, không phải danh sách item).
    dspace_solr_field_read: str = "read"
    dspace_solr_anonymous_read_token: str = "g0"
    dspace_public_base_url: str = "https://lib.hpu.edu.vn"

    dspace_service_email: str = ""
    dspace_service_password: SecretStr = SecretStr("")

    dspace_http_timeout_seconds: float = 10.0

    # --- Vector layer (Sprint 3) ---
    database_url: str = ""
    gemini_api_key: SecretStr = SecretStr("")
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_embedding_dimensions: int = 1536
    gemini_embedding_batch_size: int = 20
    gemini_http_timeout_seconds: float = 30.0
    chunk_size_chars: int = 1500
    chunk_overlap_chars: int = 200

    # --- Bóc text Tầng 2 (Sprint 4) ---
    text_extract_max_pages: int = 50

    # --- Auth / phân quyền theo API key (Sprint 4, 05-security.md) ---
    # Quy tắc CỐ ĐỊNH, không có cờ bật/tắt (xem docs/DECISIONS.md Sprint 4):
    #   - stdio  : 1 tiến trình phục vụ đúng 1 client cục bộ -> luôn coi là "internal".
    #   - streamable-http : LUÔN bắt buộc key hợp lệ qua header Authorization: Bearer.
    # Key tĩnh dùng khi CHƯA có DATABASE_URL/bảng api_keys thật (dev/demo streamable-http
    # khi chưa cắm Postgres) — rỗng thì mọi request http có kèm key đều bị từ chối.
    dev_static_api_key: SecretStr = SecretStr("")
    dev_static_api_key_scope: Literal["internal", "partner"] = "partner"
    rate_limit_default_per_minute: int = 60

    # --- MCP server ---
    mcp_transport: Literal["stdio", "streamable-http"] = "stdio"
    mcp_http_host: str = "0.0.0.0"
    mcp_http_port: int = 8800
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
