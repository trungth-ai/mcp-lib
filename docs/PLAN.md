# PLAN.md — Tiến độ hiện tại

Kế hoạch đầy đủ theo sprint: xem [../07-sprints.md](../07-sprints.md).
File này chỉ theo dõi **trạng thái sống** (sprint nào xong, đang làm gì) — cập nhật mỗi
khi kết thúc một phiên code đáng kể.

## Trạng thái: Sprint 2 xong (2026-07-02) — chờ Sprint 0 thật để xác nhận field Solr

### Đã xong
- **Sprint 0 (một phần)**: không kiểm chứng được hạ tầng thật vì máy dev Windows này
  không có route LAN tới `10.1.0.205` (curl timeout — xem CLAUDE.md → Gotchas).
  **Việc còn lại của Sprint 0** (chạy trên máy có VPN/LAN hoặc trên host `10.1.0.207`):
  - `curl http://10.1.0.205:8088/rest/communities` — REST 6.3 còn sống?
  - `curl "http://10.1.0.205:8088/solr/admin/cores?action=STATUS&wt=json"` — tên core thật.
  - `curl "http://10.1.0.205:8088/solr/search/select?q=fulltext:*&rows=0&wt=json"` — full-text đã index?
  - `curl "http://10.1.0.205:8088/solr/search/schema/fields?wt=json"` — tên field thật.
  - Thử login service account thật (`POST /rest/login`) + đọc 1 item hạn chế.
  - Kiểm hình dạng JSON thật của `/rest/items/{id}/policy` và `groupId` của nhóm Anonymous
    (code hiện giả định `0` — xem `mapping.ANONYMOUS_GROUP_ID`).
- **Sprint 1 — Lõi MCP + Provider + tools metadata**: xong, test xanh (38/38).
  - Khung FastMCP (`server.py`), config (`config.py`), logging có redaction
    (`logging_setup.py`), error handling chuẩn hóa (`errors.py`).
  - `ResourceProvider` interface + registry (`providers/base.py`, `providers/registry.py`).
  - `DSpaceProvider` + adapter 6.3 (`providers/dspace/`): auth + REST client + mapping
    DC→schema + suy diễn `access_level` (fail-safe restricted).
  - Tools: `get_item`, `list_communities`, `list_collections`, `get_recent_items`,
    `get_bitstream_link` — I/O khớp [03-tools-spec.md](../03-tools-spec.md).
  - Chạy `stdio` xác nhận được (import + `list_tools()` + smoke test lỗi mạng trả về
    đúng cấu trúc `{"error":{"code","message"}}`, không leak chi tiết nội bộ).
  - 38 unit test xanh (mapping, adapter parse 401/404/timeout, access_level, provider
    enforcement plumbing, redaction).
- **Sprint 2 — Solr search + full-text Tầng 1**: xong, test xanh (62/62 cộng dồn).
  - `providers/dspace/solr_client.py`: gọi Solr `select`, phân biệt lỗi cấu hình
    (400 → `SolrBadRequestError`, suy biến được) với lỗi hạ tầng (5xx/timeout →
    `UpstreamError`).
  - `providers/dspace/solr_search.py`: xây query (escape Lucene, filter, facet,
    highlight) + diễn giải response (facet counts, ghép highlight **theo vị trí**, không
    theo `uniqueKey` vì chưa biết định dạng thật).
  - **Thiết kế lai (hybrid)**: Solr chỉ lo tìm/lọc/rank/highlight → trả về danh sách
    `handle`; metadata + `access_level` của từng kết quả lấy lại qua REST (`provider.get()`
    đã có từ Sprint 1) — tránh phải đoán field Dublin Core trong Solr, và tự động thừa
    hưởng suy diễn `access_level` fail-safe + hậu kiểm quyền đúng theo 05-security.md §3
    ("nếu Solr không đủ tin cậy để lọc, hậu kiểm qua REST"). Item forbidden/not-found bị
    loại khỏi kết quả **âm thầm** (không lỗi cả trang) — đúng 06-test-plan §2.4.
  - `library_stats` qua Solr facet (`rows=0`), map field Solr → tên logic (`type`/`year`/
    `author`/`collection`).
  - Tools mới: `search_library`, `library_stats` — I/O khớp 03-tools-spec.md.
  - Smoke test: gọi `search_library`/`library_stats` khi Solr không kết nối được → trả
    đúng `{"error":{"code":"UPSTREAM_ERROR",...}}`, không leak chi tiết nội bộ.

### CHƯA làm (quan trọng — đừng nhầm là đã xong)
- **Chưa có tầng auth/API key thật** (Sprint 4). Tham số `allowed_levels` đã có sẵn
  trong interface nhưng server.py hiện gọi tool KHÔNG truyền `allowed_levels` (mặc định
  `None` = không lọc). **KHÔNG expose server ở trạng thái này ra ngoài Internet/đối tác.**
- Chưa test integration thật với DSpace/Solr (chỉ mock qua respx) — vì chưa có mạng LAN.
- **Tên field Solr (title/author/year/type/collection/community/default/fulltext) vẫn là
  GIẢ ĐỊNH chưa xác minh** — xem docs/DECISIONS.md mục Sprint 2. Nếu sai, `search_library`
  sẽ lỗi `UPSTREAM_ERROR` (query field sai) hoặc trả facet rỗng (facet field sai) — không
  trả sai dữ liệu âm thầm, nhưng cũng chưa hoạt động đúng cho tới khi sửa `.env`.
- `semantic_search_documents`, `get_document_text`/`find_in_document` — raise
  `NotImplementedYetError`, thuộc Sprint 3-4.
- `library_stats`/`search_library` chưa lọc theo `allowed_levels` ở tầng Solr (mới lọc
  từng kết quả `search_library` qua REST; `library_stats` hiện KHÔNG lọc theo quyền —
  xem docs/DECISIONS.md).
- Docker/Caddy/API key store/rate limit — Sprint 5.

### Tiếp theo (đề xuất)
1. Chạy nốt Sprint 0 thật trên máy có LAN — xác nhận/sửa toàn bộ field Solr trong
   `.env` (xem `.env.example` và `config.py`), `ANONYMOUS_GROUP_ID` trong `mapping.py`.
2. Sprint 3: pgvector + `EmbeddingProvider` (Gemini) + `Chunker` + `semantic_search_documents`.
