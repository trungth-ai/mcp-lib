from __future__ import annotations

import logging

from hpu_library_mcp.security.audit import audit_access


def test_audit_skips_public_access(caplog):
    with caplog.at_level(logging.INFO, logger="hpu_library_mcp.audit"):
        audit_access(item_id="123/1", access_level="public", granted=True)
    assert caplog.records == []


def test_audit_logs_internal_access_granted(caplog):
    with caplog.at_level(logging.INFO, logger="hpu_library_mcp.audit"):
        audit_access(item_id="123/1", access_level="internal", granted=True)
    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "123/1" in message
    assert "internal" in message
    assert "granted=True" in message


def test_audit_logs_restricted_access_denied(caplog):
    with caplog.at_level(logging.INFO, logger="hpu_library_mcp.audit"):
        audit_access(item_id="123/2", access_level="restricted", granted=False)
    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "granted=False" in message
