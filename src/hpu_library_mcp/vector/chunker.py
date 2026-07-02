"""Chunker — cắt văn bản dài thành đoạn cho embedding (Tầng 3, 02-architecture.md §4.3).

Cắt theo ranh giới TỪ (khoảng trắng) sau khi chuẩn hóa Unicode NFC — không bao giờ cắt
giữa 1 từ nên không thể vỡ tổ hợp dấu tiếng Việt (06-test-plan.md §2.1). Đơn vị `size`/
`overlap` là SỐ KÝ TỰ (không phải token) — đơn giản, không phụ thuộc tokenizer cụ thể.
"""

from __future__ import annotations

import unicodedata


def _joined_len(words: list[str]) -> int:
    return sum(len(w) for w in words) + max(0, len(words) - 1)  # +1 khoảng trắng mỗi từ nối


def _take_overlap_tail(words: list[str], overlap: int) -> list[str]:
    """Giữ các từ cuối của 1 chunk để làm phần chồng lấp cho chunk kế tiếp."""
    tail: list[str] = []
    for word in reversed(words):
        candidate = [word, *tail]
        if _joined_len(candidate) > overlap:
            break
        tail = candidate
    return tail


def split_text(text: str, *, size: int = 1500, overlap: int = 200) -> list[str]:
    """Cắt `text` thành các chunk tối đa ~`size` ký tự, chồng lấp ~`overlap` ký tự.

    Chunk rỗng/toàn khoảng trắng -> trả []. 1 từ đơn dài hơn `size` vẫn được giữ nguyên
    trong 1 chunk riêng (không cắt vỡ từ) — chấp nhận vượt `size` trong trường hợp hiếm này.
    """
    if size <= 0:
        raise ValueError("size phải > 0")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap phải >= 0 và < size")

    normalized = unicodedata.normalize("NFC", text or "").strip()
    if not normalized:
        return []

    words = normalized.split()
    chunks: list[str] = []
    current: list[str] = []

    for word in words:
        if current and _joined_len([*current, word]) > size:
            chunks.append(" ".join(current))
            current = _take_overlap_tail(current, overlap)
        current.append(word)

    if current:
        chunks.append(" ".join(current))

    return chunks
