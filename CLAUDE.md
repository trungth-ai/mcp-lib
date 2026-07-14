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
- Nguồn dữ liệu: **DSpace 7.6.5** REST mới (`/server/api`, HAL/HATEOAS) qua HTTPS public
  `https://lib.hpu.edu.vn/server/api` — `DSpace7Adapter` (mặc định từ 2026-07-14, HPU đã
  nâng cấp; hình dạng API đã XÁC MINH THẬT). Adapter cũ `DSpace6Adapter` (REST `/rest` +
  Solr qua LAN `10.1.0.205:8081`) vẫn giữ để rollback (`DSPACE_VERSION=6.3`).
- Vector layer: PostgreSQL + pgvector (`asyncpg`), embedding Gemini `gemini-embedding-001`
  (1536d, REST trực tiếp qua httpx — không dùng SDK `google-genai`).
- Bóc text: `pdfplumber` (chỉ PDF, thuần Python, không cần Tika/Java).
- Transport: `stdio` (dev, Claude Code/Desktop — coi là client nội bộ tin cậy) và
  `streamable-http` (prod, sau Caddy — LUÔN bắt buộc API key).
- Đóng gói: Docker (`Dockerfile` + `docker-compose.yml`, Postgres qua image
  `pgvector/pgvector:pg16`) + Caddy (`Caddyfile`, TLS tự động) — xem [docs/DEPLOY.md](docs/DEPLOY.md).
- Test: pytest + pytest-asyncio + respx (mock HTTP) + fake pool/context tự viết trong
  `tests/conftest.py` (không cần Postgres/Docker thật để chạy unit test).

## Commands
```bash
# Kích hoạt venv (Windows)
.venv\Scripts\activate           # cmd/PowerShell
source .venv/Scripts/activate    # git bash

pip install -e ".[dev]"          # cài project + dev deps
python -m pytest -q              # chạy toàn bộ test
python -m hpu_library_mcp.server     # chạy MCP server (mặc định stdio, xem .env)
python -m hpu_library_mcp.ingest     # chạy đồng bộ embedding (cần GEMINI_API_KEY + DATABASE_URL)
python -m hpu_library_mcp.admin_keys # quản lý api_keys (create/list/revoke, cần DATABASE_URL)

docker compose build && docker compose up -d   # đóng gói thật (xem docs/DEPLOY.md)
```
Copy `.env.example` → `.env` trước khi chạy server thật (không commit `.env`).

## Architecture
```
src/hpu_library_mcp/
├── server.py              — FastMCP app, đăng ký tool (10 tool) + /health, auth wiring
├── ingest.py                — pipeline đồng bộ embedding (script vận hành, không phải MCP tool)
├── admin_keys.py             — CLI quản lý api_keys (script vận hành, không phải MCP tool)
├── db.py                      — Database dùng chung (asyncpg pool + ensure_schema)
├── config.py                  — Settings (pydantic-settings, đọc .env)
├── logging_setup.py           — log có redaction + request-id/key-id/scope/allowed_levels (contextvar)
├── errors.py                   — McpToolError hierarchy -> {"error":{"code","message"}}
├── models.py                    — schema chuẩn hóa (Resource, Node, Chunk, ...) theo 04-data-model.md
├── providers/
│   ├── base.py              — interface ResourceProvider (02-architecture.md §4.1)
│   ├── registry.py          — map source -> provider instance
│   └── dspace/
│       ├── auth.py          — [6.3] login service account (/rest/login), token RAM, tự refresh
│       ├── client.py        — [6.3] HTTP client mỏng REST (get_json + get_bytes), retry 401
│       ├── mapping.py       — [6.3] DC (list phẳng) -> Resource, access_level từ policy
│       ├── solr_client.py   — [6.3] HTTP client mỏng Solr (select)
│       ├── solr_search.py   — [6.3] xây query Solr + diễn giải response (facet, highlight)
│       ├── adapter_v6.py    — DSpace6Adapter: toàn bộ chi tiết REST 6.3/Solr cụ thể
│       ├── auth_v7.py       — [7.6] login service account JWT + CSRF (/authn/login), token RAM
│       ├── client_v7.py     — [7.6] HTTP client mỏng /server/api (HAL), tham số anonymous
│       ├── mapping_v7.py    — [7.6] HAL (metadata dict + embed) -> Resource, access_level
│       │                       từ endpoint accessStatus (public vs non-public)
│       ├── adapter_v7.py    — DSpace7Adapter: /server/api + Discovery tích hợp, sort native
│       ├── adapter_base.py  — interface DSpaceAdapter (02-architecture.md §4.2, NFR-4:
│       │                       đổi phiên bản = viết adapter mới, KHÔNG sửa provider.py)
│       └── provider.py      — DSpaceProvider: CHỈ business logic dùng chung (enforce
│                               quyền, audit, orchestrate search/semantic/get_text), chọn
│                               adapter theo dspace_version, không biết REST/Solr/HAL là gì
├── vector/
│   ├── embedding.py         — interface EmbeddingProvider
│   ├── gemini_embedding.py  — GeminiEmbeddingProvider (REST Gemini, đã verify hình dạng API)
│   ├── chunker.py            — split_text (NFC-normalize, cắt theo ranh giới từ)
│   ├── queries.py            — SQL thuần pgvector (test không cần Postgres)
│   └── store.py               — VectorStore (bọc asyncpg quanh queries.py)
├── text/
│   └── extraction.py         — bóc text PDF (pdfplumber) + find_matches
└── security/
    ├── keys.py                — ApiKeyRecord, SCOPE_ALLOWED_LEVELS, Postgres/StaticApiKeyStore
    ├── rate_limit.py           — RateLimiter (sliding window, trong bộ nhớ)
    ├── resolve.py               — resolve_identity(ctx) theo transport (stdio vs http)
    └── audit.py                 — audit truy cập tài liệu internal/restricted
```

## Critical Business Rules (bất biến bảo mật — xem 05-security.md)
- **`access_level` mặc định `restricted`** khi không suy diễn được từ resource policy
  (thiếu dữ liệu, lỗi lấy policy...) — fail-safe, KHÔNG BAO GIỜ mặc định `public`.
- **Auth đã nối vào MỌI tool** (Sprint 4): `stdio` (hoặc gọi tool trực tiếp không qua
  FastMCP — script/test) = client nội bộ tin cậy; `streamable-http` = LUÔN bắt buộc
  `Authorization: Bearer <key>` hợp lệ, KHÔNG có cờ bật/tắt hay ngoại lệ. Key `partner`
  không bao giờ thấy tài liệu `internal`/`restricted` ở bất kỳ tool nào — xem
  `tests/test_security_matrix.py` (17 test, chạy thật qua `server.py`, điều kiện chặn
  merge theo 06-test-plan §2.4).
- **KHÔNG thêm tham số `allowed_levels`/quyền vào chữ ký hàm tool** — LLM client có thể
  tự set. Luôn đọc qua `logging_setup.current_allowed_levels()` (contextvar, server tự
  resolve từ key, client không set được).
- Token/mật khẩu/API key KHÔNG BAO GIỜ được log — mọi log đi qua
  `logging_setup.RedactionFilter`.
- Error trả cho client theo `{"error": {"code","message"}}`, message tiếng Việt,
  không chứa chi tiết nội bộ (host, stack trace, token...).

## Gotchas
- **[7.6] `access_level` chỉ có `public` vs `restricted`** — suy từ endpoint `accessStatus`
  (`open.access`->public, còn lại->restricted). 7.x đọc resource policy cần admin/JWT (anon
  bị 401) nên KHÔNG suy được mức `internal` như 6.3; gộp internal->restricted là AN TOÀN
  (partner vẫn chỉ thấy public, internal-key vẫn thấy cả 3 mức). Xem docs/DECISIONS.md.
- **[7.6] Chạy ẩn danh** (chưa có service account) — chỉ tải được bitstream `open.access`.
  Item restricted: anonymous thấy metadata nhưng `files=[]` (không liệt kê được bitstream)
  và không tải nội dung. Muốn internal-key đọc được nội dung tài liệu hạn chế: điền
  `DSPACE_SERVICE_EMAIL` + secret password (adapter tự login JWT qua `auth_v7.py`).
- **[7.6] `library_stats` cho partner đếm cả item metadata-public** — metadata gần như toàn
  bộ item đều discoverable với anonymous trên instance này, nên `total_items` ẩn danh ==
  tổng thật (đã đo: 32268 cả hai). KHÔNG rò rỉ nội dung (metadata vốn public trên portal),
  chỉ là con số đếm không lọc theo quyền tải — nhất quán caveat `total` thô của 6.3.
- **[7.6] Máy dev có AVG SSL-scanning (MITM)** — cert do "AVG Web/Mail Shield Root" ký,
  `certifi` không tin -> httpx báo `CERTIFICATE_VERIFY_FAILED`. CHỈ là artifact máy dev
  (server production không có AVG dùng cert thật). Muốn smoke test HTTPS local: `pip install
  truststore` rồi `truststore.inject_into_ssl()` (mượn kho tin cậy Windows). KHÔNG tắt
  verify trong code thư viện.
- **Máy Windows dev này KHÔNG có route LAN tới `10.1.0.205`**, không có Docker, không có
  `GEMINI_API_KEY` thật. Mọi test chạy bằng mock/fake (respx + fake pool trong
  `tests/conftest.py`) — CHƯA có integration test thật. Sprint 0 (trinh sát Solr/REST
  thật) phải chạy từ máy có VPN/LAN nội bộ HPU, hoặc từ host MCP `10.1.0.207`.
- Tên field Solr (`Settings.dspace_solr_field_*`, kể cả `dspace_solr_field_read`/
  `dspace_solr_anonymous_read_token` dùng lọc `library_stats`) vẫn là **GIẢ ĐỊNH CHƯA
  XÁC MINH** trên instance HPU thật. Sai thì `search_library` báo lỗi hoặc trả facet
  rỗng — không trả sai dữ liệu âm thầm (xem docs/DECISIONS.md).
- Console Windows mặc định `cp1252` — in tiếng Việt trực tiếp ra terminal PowerShell/cmd
  có thể lỗi `UnicodeEncodeError`; set `PYTHONIOENCODING=utf-8` khi cần debug qua script.
- DSpace REST 6.x: `/rest/items/{id}` cần **UUID nội bộ**, không nhận handle
  (`123456789/42`) — dùng `/rest/handle/{handle}` để resolve theo handle
  (xem `provider._resolve_item_by_id`).
- `get_recent_items` và `ingest.py` đều tải dư (over-fetch)/quét lại toàn bộ mỗi lượt vì
  REST 6.x không có tham số sort/filter theo ngày đáng tin cậy — cân nhắc chuyển sang
  Solr khi Sprint 0 xác nhận field ngày/sort đã index.
- Test bảo mật (`test_security_matrix.py`) gọi THẲNG hàm tool trong `server.py` với
  `FakeContext` (duck-type `ctx.request_context.request.headers`) — không dựng
  `mcp.server.fastmcp.Context` thật (phụ thuộc session/transport nội bộ SDK, dễ vỡ khi
  đổi version).
- **Máy này không có Docker** — `Dockerfile`/`docker-compose.yml`/`Caddyfile` viết đúng
  chuẩn nhưng CHƯA build/run thử thật. Nên test ở staging trước khi trỏ domain thật.
- pydantic-settings ưu tiên biến môi trường/`.env` HƠN Docker secret — nếu `.env` có
  dòng rỗng cho field bí mật (`GEMINI_API_KEY=`...), nó đè mất secret thật. Khi dùng
  Docker secrets, xóa hẳn các dòng đó khỏi `.env` (xem docs/DEPLOY.md mục 1).

## Shared Resources (quy ước chung mọi project HPU)
- API conventions: `~/hpu-dev/_shared/api-conventions.md` — **lưu ý**: envelope REST đó
  áp cho HTTP endpoint tự viết; MCP tool trả theo schema riêng trong
  [03-tools-spec.md](03-tools-spec.md), không dùng envelope REST.
- DB conventions: `~/hpu-dev/_shared/db-conventions.md` — áp dụng cho schema `doc_chunks`/
  `sync_state`/`api_keys`: snake_case, UTC/UTF-8, không hard delete (`api_keys.active=false`).
