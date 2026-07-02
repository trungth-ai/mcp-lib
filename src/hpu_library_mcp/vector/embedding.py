"""Interface embedding — tháo lắp được (nguyên tắc #4, 02-architecture.md §4.3).

Đổi embedding model/nhà cung cấp = viết 1 class mới implement interface này, không đụng
Chunker/VectorStore/tool semantic_search_documents.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

EmbeddingTaskType = Literal["document", "query"]


class EmbeddingProvider(ABC):
    dimensions: int

    @abstractmethod
    async def embed(self, texts: list[str], *, task_type: EmbeddingTaskType) -> list[list[float]]:
        """Trả 1 vector/text, cùng thứ tự với `texts`. `task_type` "document" khi embed
        lúc ingest, "query" khi embed câu hỏi lúc semantic_search (Gemini tối ưu khác
        nhau theo task_type — xem docs/DECISIONS.md Sprint 3)."""
