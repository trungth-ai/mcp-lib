from __future__ import annotations

import unicodedata

import pytest

from hpu_library_mcp.vector.chunker import split_text


def test_split_empty_text_returns_empty_list():
    assert split_text("") == []
    assert split_text("   \n\t  ") == []


def test_split_short_text_single_chunk():
    text = "Trường Đại học Quản lý và Công nghệ Hải Phòng."
    chunks = split_text(text, size=1000, overlap=100)
    assert chunks == [text]


def test_split_never_breaks_a_word_vietnamese():
    text = ("Trường Đại học Quản lý và Công nghệ Hải Phòng nghiên cứu ứng dụng trí tuệ nhân tạo. " * 10).strip()
    words = set(text.split())
    chunks = split_text(text, size=80, overlap=15)
    assert len(chunks) > 1
    for chunk in chunks:
        for word in chunk.split():
            assert word in words  # mọi "từ" trong chunk phải là 1 từ nguyên vẹn của văn bản gốc


def test_split_respects_max_size_when_possible():
    text = ("tu " * 200).strip()
    chunks = split_text(text, size=50, overlap=10)
    for chunk in chunks[:-1]:  # chunk cuối có thể ngắn hơn
        assert len(chunk) <= 50


def test_split_zero_overlap_no_repeated_words_between_chunks():
    text = ("mot hai ba bon nam sau bay tam chin muoi " * 10).strip()
    chunks = split_text(text, size=30, overlap=0)
    assert len(chunks) > 1
    for a, b in zip(chunks, chunks[1:]):
        assert a.split()[-1] != b.split()[0]


def test_split_overlap_repeats_tail_words():
    text = " ".join(f"tu{i}" for i in range(30))
    chunks = split_text(text, size=20, overlap=10)
    assert len(chunks) > 1
    # từ cuối chunk trước phải xuất hiện ở đầu chunk sau (overlap thật sự diễn ra)
    assert chunks[0].split()[-1] in chunks[1].split()


def test_split_normalizes_unicode_nfc():
    composed = unicodedata.normalize("NFC", "tuyển sinh đại học")
    decomposed = unicodedata.normalize("NFD", composed)
    assert decomposed != composed  # xác nhận 2 dạng thật sự khác byte nhau

    chunks = split_text(decomposed, size=100, overlap=10)
    assert unicodedata.is_normalized("NFC", chunks[0])
    assert chunks[0] == composed


def test_split_invalid_size_raises():
    with pytest.raises(ValueError):
        split_text("abc", size=0, overlap=0)


def test_split_overlap_gte_size_raises():
    with pytest.raises(ValueError):
        split_text("abc", size=10, overlap=10)
    with pytest.raises(ValueError):
        split_text("abc", size=10, overlap=-1)


def test_split_single_word_longer_than_size_kept_whole():
    long_word = "a" * 500
    chunks = split_text(f"{long_word} tiep theo", size=50, overlap=5)
    assert chunks[0] == long_word
