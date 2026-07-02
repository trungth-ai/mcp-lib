from __future__ import annotations

import pytest

from hpu_library_mcp.errors import ExtractionError, UnsupportedFormatError
from hpu_library_mcp.text.extraction import extract_pages, find_matches
from tests.conftest import MINIMAL_PDF_BYTES


def test_extract_pages_happy_path():
    pages, truncated = extract_pages(MINIMAL_PDF_BYTES, mime="application/pdf", max_pages=10)
    assert pages == ["Hello World"]
    assert truncated is False


def test_extract_pages_unsupported_mime_raises():
    with pytest.raises(UnsupportedFormatError):
        extract_pages(b"data", mime="application/msword", max_pages=10)


def test_extract_pages_corrupt_pdf_raises_extraction_error():
    with pytest.raises(ExtractionError):
        extract_pages(b"not a real pdf", mime="application/pdf", max_pages=10)


def test_extract_pages_truncates_when_over_max_pages(monkeypatch):
    class FakePage:
        def extract_text(self):
            return "trang"

    class FakePdf:
        pages = [FakePage() for _ in range(5)]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    import hpu_library_mcp.text.extraction as extraction_module

    monkeypatch.setattr(extraction_module.pdfplumber, "open", lambda _stream: FakePdf())
    pages, truncated = extraction_module.extract_pages(b"fake", mime="application/pdf", max_pages=3)
    assert len(pages) == 3
    assert truncated is True


def test_find_matches_case_insensitive():
    text = "Trường Đại học tổ chức TUYỂN SINH năm 2026."
    matches = find_matches(text, "tuyển sinh")
    assert len(matches) == 1
    assert "TUYỂN SINH" in matches[0]


def test_find_matches_no_match_returns_empty():
    assert find_matches("nội dung không liên quan", "tuyển sinh") == []


def test_find_matches_empty_query_or_text_returns_empty():
    assert find_matches("", "tuyển sinh") == []
    assert find_matches("nội dung", "") == []


def test_find_matches_multiple_occurrences():
    text = "học máy là gì, học máy dùng để làm gì"
    matches = find_matches(text, "học máy", context_chars=5)
    assert len(matches) == 2
