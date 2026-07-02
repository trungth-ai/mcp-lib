"""Bóc text từ bitstream — Tầng 2 (03-tools-spec.md get_document_text/find_in_document).

Chỉ hỗ trợ PDF qua pdfplumber (thuần Python, không cần Tika/Java) ở Sprint 4 — xem
docs/DECISIONS.md lý do chọn pdfplumber thay Tika. Định dạng khác (docx, ...) báo lỗi rõ
ràng `UnsupportedFormatError`, không cố đoán/bóc sai.
"""

from __future__ import annotations

import io

import pdfplumber

from hpu_library_mcp.errors import ExtractionError, UnsupportedFormatError
from hpu_library_mcp.logging_setup import get_logger

logger = get_logger(__name__)

SUPPORTED_MIME_TYPES = {"application/pdf"}


def extract_pages(content: bytes, *, mime: str, max_pages: int) -> tuple[list[str], bool]:
    """Trả (text từng trang theo thứ tự, truncated). Trang không có text -> chuỗi rỗng
    (giữ đúng số thứ tự trang 1-based khi client truyền `page`)."""
    if mime not in SUPPORTED_MIME_TYPES:
        raise UnsupportedFormatError(mime)

    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            total_pages = len(pdf.pages)
            truncated = total_pages > max_pages
            texts = [(page.extract_text() or "") for page in pdf.pages[:max_pages]]
    except UnsupportedFormatError:
        raise
    except Exception as exc:  # pdfminer/pdfplumber ném nhiều loại lỗi khác nhau khi PDF hỏng
        logger.warning("pdf_extract_failed")
        raise ExtractionError() from exc

    return texts, truncated


def find_matches(text: str, query: str, *, context_chars: int = 80) -> list[str]:
    """Tìm các đoạn khớp `query` (không phân biệt hoa/thường) trong `text`, trả đoạn
    trích kèm ngữ cảnh xung quanh. Tìm mờ theo dấu tiếng Việt là việc của Tầng 1 (Solr)."""
    if not query or not text:
        return []
    text_lower = text.lower()
    query_lower = query.lower()
    matches: list[str] = []
    start = 0
    while True:
        idx = text_lower.find(query_lower, start)
        if idx == -1:
            break
        snippet_start = max(0, idx - context_chars)
        snippet_end = min(len(text), idx + len(query) + context_chars)
        matches.append(text[snippet_start:snippet_end])
        start = idx + max(1, len(query_lower))
    return matches
