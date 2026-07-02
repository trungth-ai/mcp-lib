# HPU Library MCP Server — CLAUDE.md

## Project Overview
MCP Server (FastMCP, Python) biến thư viện số DSpace `lib.hpu.edu.vn` thành nguồn
tri thức mà RAG chatbot, agent tuyển sinh, Claude Code, đối tác ngoài gọi qua 1 cổng
duy nhất, có phân quyền theo API key. Xem bộ tài liệu kế hoạch: [README.md](README.md)
và [01](01-requirements.md)–[07](07-sprints.md).

**Trước khi sửa gì phức tạp: đọc [docs/PLAN.md](docs/PLAN.md) (tiến độ sprint hiện tại)
và [docs/DECISIONS.md](docs/DECISIONS.md) (quyết định implementation).**

## Tech Stack
- Python 3.12, FastMCP (`mcp` SDK chính thức), httpx (async), Pydantic v2 + pydantic-settings.
- Nguồn dữ liệu: DSpace 6.3 REST cũ (`/rest`) qua LAN `10.1.0.205:8088`.
- Vector layer (Sprint 3, chưa code): PostgreSQL + pgvector, embedding Gemini `gemini-embedding-001` (1536d).
- Transport: `stdio` (dev, Claude Code/Desktop) và `streamable-http` (prod, sau Caddy) — Sprint 5.
- Test: pytest + pytest-asyncio + respx (mock httpx, không gọi mạng thật ở unit test).

## Commands
```bash
# Kích hoạt venv (Windows)
.venv\Scripts\activate           # cmd/PowerShell
source .venv/Scripts/activate    # git bash

pip install -e ".[dev]"          # cài project + dev deps
python -m pytest -q              # chạy toàn bộ test
python -m hpu_library_mcp.server # chạy server (mặc định stdio, xem .env)
```
Copy `.env.example` → `.env` trước khi chạy server thật (không commit `.env`).

## Architecture
```
src/hpu_library_mcp/
├── server.py              — FastMCP app, đăng ký tool, composition root
├── config.py               — Settings (pydantic-settings, đọc .env)
├── logging_setup.py        — log có redaction + request-id/key-id/tool context
├── errors.py                — McpToolError hierarchy -> {"error":{"code","message"}}
├── models.py                 — schema chuẩn hóa (Resource, Node, Chunk, ...) theo 04-data-model.md
├── providers/
│   ├── base.py             — interface ResourceProvider (02-architecture.md §4.1)
│   ├── registry.py         — map source -> provider instance
│   └── dspace/
│       ├── auth.py         — login service account, giữ token trong RAM, tự refresh
│       ├── client.py       — HTTP client mỏng, retry 1 lần khi 401
│       ├── mapping.py      — DC -> Resource, suy diễn access_level (05-security.md §4)
│       └── provider.py     — DSpaceProvider, hiện thực ResourceProvider cho DSpace 6.3
└── tests/                   — unit test (mock HTTP bằng respx, không cần mạng)
```

## Critical Business Rules (bất biến bảo mật — xem 05-security.md)
- **`access_level` mặc định `restricted`** khi không suy diễn được từ resource policy
  (thiếu dữ liệu, lỗi lấy policy...) — fail-safe, KHÔNG BAO GIỜ mặc định `public`.
- Key `partner` (Sprint 4, CHƯA hiện thực) không bao giờ được thấy tài liệu
  `internal`/`restricted` ở bất kỳ tool nào.
- Token/mật khẩu KHÔNG BAO GIỜ được log — mọi log đi qua `logging_setup.RedactionFilter`.
- Error trả cho client theo `{"error": {"code","message"}}`, message tiếng Việt,
  không chứa chi tiết nội bộ (host, stack trace...).

## Gotchas
- **Máy Windows dev này KHÔNG có route LAN tới `10.1.0.205`** (đã thử `curl`, timeout).
  Sprint 0 (trinh sát Solr/REST thật) phải chạy từ máy có VPN/LAN nội bộ HPU, hoặc từ
  host MCP `10.1.0.207`. Cho tới khi đó, các giá trị sau vẫn là **GIẢ ĐỊNH CHƯA XÁC MINH**
  (đã để trong config, không hardcode): tên Solr core (`search`), tên field full-text
  (`fulltext`), hình dạng JSON `/rest/items/.../policy`, `ANONYMOUS_GROUP_ID = 0`.
- Console Windows mặc định `cp1252` — in tiếng Việt trực tiếp ra terminal PowerShell/cmd
  có thể lỗi `UnicodeEncodeError`; set `PYTHONIOENCODING=utf-8` khi cần debug qua script.
- DSpace REST 6.x: `/rest/items/{id}` cần **UUID nội bộ**, không nhận handle
  (`123456789/42`) — dùng `/rest/handle/{handle}` để resolve theo handle
  (xem `provider._resolve_item_by_id`).
- `get_recent_items` hiện tại tải dư (over-fetch) rồi sort phía client vì REST 6.x
  không có tham số sort theo ngày đáng tin cậy — cân nhắc chuyển sang Solr khi Sprint 2
  xác nhận full-text/sort đã index.

## Shared Resources (quy ước chung mọi project HPU)
- API conventions: `~/hpu-dev/_shared/api-conventions.md` — **lưu ý**: envelope REST đó
  áp cho HTTP endpoint tự viết; MCP tool trả theo schema riêng trong
  [03-tools-spec.md](03-tools-spec.md), không dùng envelope REST.
- DB conventions: `~/hpu-dev/_shared/db-conventions.md` — áp dụng cho schema `doc_chunks`/
  `api_keys` (Sprint 3-4): snake_case, UTC/UTF-8, không hard delete (`api_keys.active=false`).
