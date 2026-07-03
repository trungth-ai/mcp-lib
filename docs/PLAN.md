# PLAN.md — Tiến độ hiện tại

Kế hoạch đầy đủ theo sprint: xem [../07-sprints.md](../07-sprints.md).
File này chỉ theo dõi **trạng thái sống** (sprint nào xong, đang làm gì) — cập nhật mỗi
khi kết thúc một phiên code đáng kể.

## Trạng thái: Sprint 5 + rà soát lỗ hổng xong (2026-07-03) — GĐ1 code xong hết cả 6 sprint

### Deploy thật lần đầu (2026-07-03) — đang chặn ở tầng mạng, không phải code

Anh Trung deploy thử lên host thật (ubuntu210, chạy Docker), gặp 2 vấn đề:

1. **Crash loop `MCP_TRANSPORT=stdio` trong container** — đã sửa (xem mục "Fix" bên
   dưới, commit `c29db40`): ép cứng `streamable-http` trong `docker-compose.yml`.
2. **Không kết nối được DSpace REST từ host MCP tới host DSpace** — đã xác nhận:
   - Cổng REST thật là **8081**, không phải 8088 (giả định cũ, đã sửa `config.py`/
     `.env.example`/`CLAUDE.md`). Xác nhận qua browser mở được
     `http://localhost:8081/rest` **trên chính host DSpace (10.1.0.205)**.
   - Từ host MCP (`ubuntu210`) gọi `curl -m 3 http://10.1.0.205:8081/solr` → **timeout**
     (không phải "connection refused") — dấu hiệu firewall/network DROP giữa 2 host,
     không phải DSpace service chết hay code sai.
   - `ufw status` trên `ubuntu210` (phía client/MCP) là `inactive` → chặn không phải ở
     phía này.
   - **Nghi vấn chính**: Windows Firewall trên host DSpace (`10.1.0.205` — theo
     README.md, host này chạy Windows) chỉ cho phép `127.0.0.1`, chặn inbound từ IP LAN
     khác trên cổng 8081. Anh Trung đang tự kiểm tra trực tiếp trên host đó (có mở sẵn
     `traefik.toml`, `rules.toml`, `dspace.cfg` qua Notepad++ — có vẻ Traefik là lớp
     trước DSpace, có thể route hiện tại chỉ cho phép qua Traefik chứ không mở thẳng LAN).
   - **Cổng Solr thật vẫn CHƯA xác nhận** — mới chỉ giả định dùng chung cổng REST
     (8081), cần kiểm riêng (curl trực tiếp từ host DSpace vào chính nó trước, như đã
     làm với `/rest`, để loại trừ vấn đề mạng khỏi câu hỏi "cổng nào").

**Việc này KHÔNG sửa được bằng code** — cần anh Trung/quản trị mạng HPU xử lý ở tầng hạ
tầng (Windows Firewall, hoặc rule Traefik nếu ý định là mọi truy cập phải qua Traefik).

### Rà soát lỗ hổng (sau Sprint 5, 2026-07-03)
Soát lại toàn bộ 01/03/06 so với code thật, phát hiện + sửa 4 lỗ hổng:

1. **Tách `DSpaceAdapter`** (`adapter_base.py` + `adapter_v6.py`) khỏi `DSpaceProvider` —
   trước đây `DSpaceProvider` chứa thẳng logic REST 6.3/Solr, `Settings.dspace_version`
   tồn tại nhưng KHÔNG ĐƯỢC DÙNG (config chết) → vi phạm NFR-4 ("chuyển 6.3→v10 chỉ đổi
   config adapter, không sửa tool"). Giờ `DSpaceProvider` chỉ còn business logic
   (enforce/audit/orchestrate), gọi qua interface `DSpaceAdapter`; `dspace_version=v10`
   giờ báo lỗi rõ ràng (`NotImplementedYetError`) thay vì âm thầm dùng nhầm adapter 6.3.
   195/195 test cũ (trước refactor: 181) vẫn xanh KHÔNG SỬA GÌ trong test — xác nhận hành
   vi không đổi, chỉ tái cấu trúc.
2. **`semantic_search_documents` giờ ghi audit** cho chunk `internal`/`restricted` trả
   về (trước đây chỉ lọc bằng SQL, không audit — thiếu so với 05-security.md §6).
3. **Test "MCP contract"** (06-test-plan §2.2, `tests/test_mcp_contract.py`): xác nhận tự
   động đúng 10 tool + schema khớp 03-tools-spec.md + `ctx` không lộ ra client + app
   streamable-http dựng được và `/health` gọi được không cần key.
4. **Test rate limit qua đúng đường `server.py`** (06-test-plan §2.5,
   `tests/test_rate_limit_integration.py`) + **test hiệu năng dạng proxy** (NFR-3,
   `tests/test_performance_bounds.py`: chặn trên số lượt REST/Solr, và đo trực tiếp
   `search()` chạy SONG SONG không tuần tự bằng độ trễ giả lập — phát hiện được nếu ai
   đó lỡ đổi `asyncio.gather` thành vòng lặp `await`).

Còn 3 điểm nhỏ **CHƯA sửa** (cần xác nhận ý định trước khi đổi API, không tự ý đổi):
- `citations` chỉ có ở `search_library`/`semantic_search_documents`, không có ở 8 tool
  còn lại (03-tools-spec.md nói "mọi output kèm citations" nhưng ví dụ JSON cụ thể chỉ
  2 tool có).
- `get_recent_items` trả `{"items":[...]}` với `Resource` đầy đủ, spec nói "danh sách
  Resource **rút gọn**" (có thể ý là mảng trần + ít field hơn).
- `library_stats` mặc định `group_by=["type","year"]`, spec ví dụ có thêm `"collection"`.

### Đã xong

**Sprint 0 (một phần)** — không kiểm chứng được hạ tầng thật vì máy dev Windows này
không có route LAN tới `10.1.0.205` (curl timeout — xem CLAUDE.md → Gotchas). Việc còn
lại: chạy các lệnh `curl` trong [07-sprints.md](../07-sprints.md) Sprint 0 từ máy có
VPN/LAN nội bộ HPU hoặc từ host `10.1.0.207`, rồi sửa `.env` theo kết quả thật (KHÔNG
cần sửa code — mọi giả định đã đưa vào config).

**Sprint 1 — Lõi MCP + Provider + tools metadata**: `get_item`, `list_communities`,
`list_collections`, `get_recent_items`, `get_bitstream_link`.

**Sprint 2 — Solr search + full-text Tầng 1**: `search_library`, `library_stats`. Thiết
kế lai (Solr tìm/lọc/rank, REST cấp metadata + access_level chính xác).

**Sprint 3 — Ngữ nghĩa Tầng 3 (pgvector)**:
- `vector/embedding.py` (interface) + `vector/gemini_embedding.py`: gọi
  `POST .../models/gemini-embedding-001:batchEmbedContents`, header `x-goog-api-key`,
  `output_dimensionality`/`task_type` (RETRIEVAL_DOCUMENT lúc ingest, RETRIEVAL_QUERY lúc
  search) — **hình dạng REST API đã xác minh qua tài liệu chính thức + cookbook Google
  (WebFetch), KHÁC các giả định DSpace/Solr** (API công khai, ổn định).
- `vector/chunker.py`: cắt theo ranh giới từ sau NFC-normalize, không vỡ tổ hợp dấu
  tiếng Việt.
- `db.py`: 1 `Database` (asyncpg pool) dùng chung cho `doc_chunks`/`sync_state`
  (Sprint 3) và `api_keys` (Sprint 4), `ensure_schema()` idempotent đúng SQL
  04-data-model.md.
- `vector/queries.py` (SQL thuần, test không cần Postgres) + `vector/store.py`
  (`VectorStore`): upsert idempotent, `semantic_search` có `access_level = ANY($3)`.
- `DSpaceProvider.semantic_search()` + tool `semantic_search_documents`.
- `ingest.py`: pipeline đồng bộ (lấy item → bóc text Tầng 2 → chunk → embed theo lô →
  upsert) — **best-effort, CHƯA chạy được thật** (không có Postgres/GEMINI_API_KEY/LAN ở
  máy này), chỉ test bằng fake. `python -m hpu_library_mcp.ingest` báo lỗi rõ ràng khi
  thiếu cấu hình thay vì crash mơ hồ.

**Sprint 4 — Bóc text Tầng 2 + phân tầng quyền theo API key**:
- `text/extraction.py` (pdfplumber, chỉ PDF) + `DSpaceRestClient.get_bytes()`.
- `DSpaceProvider.get_text()` + tool `get_document_text`/`find_in_document` — LUÔN gọi
  `self.get()` trước để enforce quyền + ghi audit trước khi bóc bất kỳ nội dung nào.
- `security/audit.py`: audit mọi lần chạm tài liệu `internal`/`restricted` (key-id +
  item-id + granted/denied), nối qua `_enforce_access` trong provider (dùng chung cho
  `get`, `get_recent_items`, `search`, `get_bitstream_link`, `get_text`).
- `security/keys.py`: `hash_api_key` (sha256, không lưu key thô), `SCOPE_ALLOWED_LEVELS`
  (partner→public; internal→cả 3), `PostgresApiKeyStore` + `StaticApiKeyStore` (dev khi
  chưa có Postgres).
- `security/rate_limit.py`: sliding window trong bộ nhớ theo key-id (đủ 1 instance).
- `security/resolve.py`: **quy tắc cố định theo transport** — stdio (hoặc gọi trực tiếp
  không qua FastMCP) = client nội bộ cục bộ; streamable-http = LUÔN bắt buộc
  `Authorization: Bearer <key>` hợp lệ, không có ngoại lệ/cờ bật-tắt.
- **MỌI tool trong server.py** giờ nhận `ctx: Context`, resolve identity qua
  `resolve_identity()`, truyền `allowed_levels=current_allowed_levels()` vào provider.
  `library_stats` lọc thêm ở Solr qua field `read` khi key chỉ thấy `public` (không có
  REST hậu kiểm từng item như search vì stats là facet count).
- Bộ test bảo mật đầy đủ theo 06-test-plan §2.4 (`tests/test_security_matrix.py`, 17
  test) chạy THẬT qua tool `server.py` (không chỉ ở tầng provider): partner bị loại
  khỏi `search_library`/`get_recent_items`/`library_stats`, bị `forbidden` ở
  `get_item`/`get_bitstream_link`/`get_document_text`/`find_in_document`; internal thấy
  đủ; không có key qua streamable-http luôn bị chặn; response lỗi không lộ token.

**Sprint 5 — Đóng gói & phục vụ**:
- `Dockerfile` (multi-stage nhẹ, non-root user, `HEALTHCHECK` gọi `/health`), `.dockerignore`.
- `docker-compose.yml`: service `mcp` + `postgres` (`pgvector/pgvector:pg16`), Docker
  secrets cho `database_url`/`dspace_service_password`/`gemini_api_key`/`dev_static_api_key`
  (mẫu `.example` trong `secrets/`, file thật bị gitignore).
- `Caddyfile`: reverse proxy `mcp-lib.hpu.edu.vn` → `127.0.0.1:8800`.
- `GET /health` (không cần API key, dùng `mcp.custom_route` — xác nhận có thật trong SDK
  đã cài): báo trạng thái DSpace REST + đã cấu hình semantic search/key store chưa.
- `admin_keys.py` (`python -m hpu_library_mcp.admin_keys create|list|revoke`): tạo/liệt
  kê/khóa `api_keys` trực tiếp trên Postgres, key thô chỉ hiện 1 lần lúc tạo.
- `docs/DEPLOY.md`: quy trình build/run/rotate key/chạy lại đồng bộ + bảng sự cố thường
  gặp, đặc biệt lưu ý thứ tự ưu tiên `.env` > Docker secret của pydantic-settings (dễ
  đè mất secret nếu để sót dòng rỗng trong `.env`).
- **181 unit test xanh** (cộng dồn cả 5 sprint).

### CHƯA làm (quan trọng — đừng nhầm là đã xong)
- **Tên field Solr** (title/author/year/type/default/fulltext/read...) vẫn là GIẢ ĐỊNH
  chưa xác minh trên instance HPU thật — đã đưa hết vào `.env`, không cần sửa code khi
  có kết quả Sprint 0 thật.
- **Chưa build/run Docker thật** — máy dev Windows này không có Docker. Dockerfile/
  compose/Caddyfile viết đúng theo chuẩn nhưng CHƯA build thử; nên chạy ở staging trước
  khi trỏ domain thật.
- **Chưa chạy được integration thật** với DSpace/Solr/Postgres/Gemini (chỉ mock/fake) —
  máy dev này không có LAN, Docker, hay `GEMINI_API_KEY` thật.
- `library_stats` cho key `partner`: lọc qua Solr field `read` (token `g0`) — CHƯA xác
  minh token/field này đúng trên instance thật (khác cơ chế `access_level` suy từ REST
  policy, dùng trực tiếp field nội bộ Solr).
- `search()`/`semantic_search()` chưa hỗ trợ `filters` đầy đủ như spec (vd
  `semantic_search_documents` chưa lọc theo collection/year/type — xem
  docs/DECISIONS.md).
- Chưa gỡ chunk pgvector khi item bị ẩn/xóa ở DSpace (ingest chỉ upsert, chưa so sánh
  2 chiều).
- Rate limit chỉ đúng cho 1 instance (trong bộ nhớ) — cần Redis/Postgres nếu scale ngang
  nhiều container `mcp` cùng lúc.

### Tiếp theo (đề xuất)
1. Chạy nốt Sprint 0 thật trên máy có LAN — xác nhận/sửa toàn bộ field Solr trong
   `.env`, `ANONYMOUS_GROUP_ID` trong `mapping.py`.
2. Build + chạy thử `docker compose` ở staging (host có Docker) trước khi deploy thật
   lên `10.1.0.207` — xem docs/DEPLOY.md.
3. Nếu có Postgres+pgvector và `GEMINI_API_KEY` thật: chạy `hpu-library-mcp-sync` với
   vài item mẫu, xác nhận `semantic_search_documents` trả đúng + đo chi phí embedding
   (NFR-8) trước khi ingest toàn kho.
4. Tạo `api_keys` thật cho từng client (RAG chatbot, agent tuyển sinh, đối tác ngoài)
   qua `admin_keys.py`, thay `DEV_STATIC_API_KEY`.
