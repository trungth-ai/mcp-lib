"""Interface DSpaceAdapter — tách phần THẬT SỰ phụ thuộc phiên bản DSpace (đường REST cụ
thể, field Solr, hình dạng JSON) khỏi `DSpaceProvider` (business logic dùng chung: enforce
quyền, audit, orchestrate) — đúng 02-architecture.md §4.2:

    "DSpaceProvider hiện thực interface, ủy quyền cho adapter phiên bản.
     Thêm nguồn mới = viết 1 class theo interface + đăng ký registry."

Đổi 6.3 → v10 (NFR-4, 01-requirements.md) = viết 1 class mới implement interface này,
KHÔNG sửa `DSpaceProvider` hay bất kỳ tool nào trong `server.py`. Mọi method trả object
ĐÃ CHUẨN HÓA (`Resource`/`Node`/`ResourceFile`) — provider không cần biết đang nói chuyện
với REST 6.x hay `/server/api` v10.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from hpu_library_mcp.models import Health, Node, Resource, ResourceFile


class DSpaceAdapter(ABC):
    @abstractmethod
    async def resolve_item(self, id: str) -> Resource:
        """Lấy 1 item theo handle/uuid, đã map + suy diễn access_level. NotFoundError nếu
        không có — KHÔNG enforce quyền ở đây (việc của DSpaceProvider)."""

    @abstractmethod
    async def list_communities(self, *, parent: str | None) -> list[Node]: ...

    @abstractmethod
    async def list_collections(self, *, parent: str | None) -> list[Node]: ...

    @abstractmethod
    async def list_recent_candidates(self, *, collection: str | None, limit: int) -> list[Resource]:
        """Đã sắp xếp giảm dần theo ngày nạp (hoặc tương đương) VÀ đã cắt còn đúng
        `limit` — DSpaceProvider chỉ còn việc enforce/audit từng cái."""

    @abstractmethod
    async def get_bitstream(self, item_id: str, bitstream_id: str) -> ResourceFile:
        """NotFoundError nếu item hoặc bitstream không tồn tại."""

    @abstractmethod
    async def download_bitstream_bytes(self, file: ResourceFile) -> bytes: ...

    @abstractmethod
    async def search_candidates(
        self,
        *,
        query: str,
        scope: str,
        filters: dict[str, Any] | None,
        facets: list[str] | None,
        page: int,
        page_size: int,
    ) -> tuple[int, list[tuple[str, list[str]]], dict[str, dict[str, int]]]:
        """Trả (total thô theo nguồn, [(id_item, highlight_snippets)], facets theo TÊN
        LOGIC vd "type"/"year" — adapter tự dịch từ tên field nội bộ của mình)."""

    @abstractmethod
    async def stats_facets(
        self, *, group_by: list[str], allowed_levels: tuple[str, ...] | None
    ) -> tuple[int, dict[str, dict[str, int]]]:
        """Trả (total_items, facets theo tên logic). `allowed_levels` truyền vào để adapter
        tự quyết định lọc thêm ở tầng nguồn hay không (vd Solr field `read`) — DSpaceProvider
        không biết field/cơ chế nội bộ đó, chỉ biết "key này được thấy các mức nào"."""

    @abstractmethod
    async def health(self) -> Health: ...

    @abstractmethod
    async def aclose(self) -> None: ...
