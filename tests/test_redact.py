from __future__ import annotations

from hpu_library_mcp.logging_setup import redact_text


def test_redact_masks_password_field():
    redacted = redact_text("login failed password=SuperSecret123")
    assert "SuperSecret123" not in redacted
    assert "***REDACTED***" in redacted


def test_redact_masks_bearer_token():
    redacted = redact_text("Authorization: Bearer abc.def.ghi")
    assert "abc.def.ghi" not in redacted


def test_redact_masks_rest_dspace_token():
    redacted = redact_text("rest-dspace-token: 1234567890abcdef")
    assert "1234567890abcdef" not in redacted


def test_redact_masks_api_key_field():
    redacted = redact_text("gemini_api_key=AIzaSyFAKEKEYVALUE")
    assert "AIzaSyFAKEKEYVALUE" not in redacted


def test_redact_masks_extra_secret_substring():
    redacted = redact_text("connecting with key myXsecretY", extra_secrets=["myXsecretY"])
    assert "myXsecretY" not in redacted


def test_redact_leaves_normal_vietnamese_text_untouched():
    text = "tìm thấy 12 tài liệu cho từ khóa 'tuyển sinh'"
    assert redact_text(text) == text


def test_redact_handles_empty_and_none():
    assert redact_text("") == ""
    assert redact_text(None) is None
