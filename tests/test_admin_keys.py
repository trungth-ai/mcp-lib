from __future__ import annotations

import pytest

from hpu_library_mcp.admin_keys import _build_parser, _create, _list, _revoke
from hpu_library_mcp.security.keys import hash_api_key
from tests.conftest import FakeAsyncpgConn, FakeDatabase


def test_parser_create_requires_label_and_scope():
    parser = _build_parser()
    args = parser.parse_args(["create", "--label", "RAG chatbot", "--scope", "internal"])
    assert args.command == "create"
    assert args.label == "RAG chatbot"
    assert args.scope == "internal"
    assert args.rate_limit is None


def test_parser_create_rejects_unknown_scope():
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["create", "--label", "x", "--scope", "super-admin"])


def test_parser_revoke_requires_key_id():
    parser = _build_parser()
    args = parser.parse_args(["revoke", "key_abc123"])
    assert args.key_id == "key_abc123"


async def test_create_inserts_hashed_key_not_raw(capsys):
    conn = FakeAsyncpgConn()
    database = FakeDatabase(conn)
    await _create(database, label="Đối tác X", scope="partner", rate_limit=30)

    sql, args = conn.executed[0]
    assert "INSERT INTO api_keys" in sql
    key_id, key_hash, label, scope, rate_limit, _created_at = args
    assert label == "Đối tác X"
    assert scope == "partner"
    assert rate_limit == 30

    printed = capsys.readouterr().out
    assert key_id in printed
    assert "KEY THÔ" in printed
    raw_key_line = next(line for line in printed.splitlines() if "KEY THÔ" in line)
    raw_key = raw_key_line.split(": ", 1)[1]
    # key thô in ra đúng khớp hash đã lưu, nhưng bản thân key thô không được lưu trong DB
    assert hash_api_key(raw_key) == key_hash
    assert raw_key != key_hash


async def test_list_prints_all_keys(capsys):
    rows = [
        {
            "id": "key_1",
            "label": "RAG",
            "scope": "internal",
            "rate_limit": 100,
            "active": True,
            "created_at": "2026-01-01",
        }
    ]
    database = FakeDatabase(FakeAsyncpgConn(fetch_result=rows))
    await _list(database)
    printed = capsys.readouterr().out
    assert "key_1" in printed
    assert "internal" in printed


async def test_list_empty_prints_placeholder(capsys):
    database = FakeDatabase(FakeAsyncpgConn(fetch_result=[]))
    await _list(database)
    printed = capsys.readouterr().out
    assert "chưa có key" in printed


class _RevokeConn(FakeAsyncpgConn):
    def __init__(self, result: str) -> None:
        super().__init__()
        self._result = result

    async def execute(self, sql: str, *args) -> str:
        self.executed.append((sql, args))
        return self._result


async def test_revoke_executes_update_with_key_id():
    conn = _RevokeConn("UPDATE 1")
    await _revoke(FakeDatabase(conn), "key_1")
    sql, args = conn.executed[0]
    assert "UPDATE api_keys SET active = false" in sql
    assert args == ("key_1",)


async def test_revoke_unknown_key_exits_nonzero():
    conn = _RevokeConn("UPDATE 0")
    with pytest.raises(SystemExit):
        await _revoke(FakeDatabase(conn), "khong-ton-tai")
