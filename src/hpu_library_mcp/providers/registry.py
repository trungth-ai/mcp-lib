"""Registry nguồn -> ResourceProvider (nguyên tắc #2, NFR-7 khả mở).

Thêm nguồn mới = gọi register() với 1 instance provider mới, không đụng tools/lõi.
"""

from __future__ import annotations

from hpu_library_mcp.errors import ValidationError
from hpu_library_mcp.providers.base import ResourceProvider


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, ResourceProvider] = {}

    def register(self, provider: ResourceProvider) -> None:
        self._providers[provider.source] = provider

    def get(self, source: str) -> ResourceProvider:
        provider = self._providers.get(source)
        if provider is None:
            known = ", ".join(sorted(self._providers)) or "(chưa có nguồn nào)"
            raise ValidationError(f"Nguồn '{source}' không tồn tại. Các nguồn hỗ trợ: {known}.")
        return provider

    def sources(self) -> list[str]:
        return sorted(self._providers)
