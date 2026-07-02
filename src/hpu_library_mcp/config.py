from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- DSpace ---
    dspace_version: Literal["6.3", "v10"] = "6.3"
    dspace_rest_base_url: str = "http://10.1.0.205:8088/rest"
    dspace_solr_base_url: str = "http://10.1.0.205:8088/solr"
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
    dspace_public_base_url: str = "https://lib.hpu.edu.vn"

    dspace_service_email: str = ""
    dspace_service_password: SecretStr = SecretStr("")

    dspace_http_timeout_seconds: float = 10.0

    # --- Vector layer (Sprint 3) ---
    database_url: str = ""
    gemini_api_key: SecretStr = SecretStr("")

    # --- MCP server ---
    mcp_transport: Literal["stdio", "streamable-http"] = "stdio"
    mcp_http_host: str = "0.0.0.0"
    mcp_http_port: int = 8800
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
