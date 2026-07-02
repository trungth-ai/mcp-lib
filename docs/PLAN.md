# PLAN.md — Tiến độ hiện tại

Kế hoạch đầy đủ theo sprint: xem [../07-sprints.md](../07-sprints.md).
File này chỉ theo dõi **trạng thái sống** (sprint nào xong, đang làm gì) — cập nhật mỗi
khi kết thúc một phiên code đáng kể.

## Trạng thái: Sprint 1 xong (2026-07-02) — chờ Sprint 0 thật + duyệt Sprint 2

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

### CHƯA làm (quan trọng — đừng nhầm là đã xong)
- **Chưa có tầng auth/API key thật** (Sprint 4). Tham số `allowed_levels` đã có sẵn
  trong interface nhưng server.py hiện gọi tool KHÔNG truyền `allowed_levels` (mặc định
  `None` = không lọc). **KHÔNG expose server ở trạng thái này ra ngoài Internet/đối tác.**
- Chưa test integration thật với DSpace (chỉ mock qua respx) — vì chưa có mạng LAN.
- `search_library`, `semantic_search_documents`, `get_document_text`/`find_in_document`,
  `library_stats` — raise `NotImplementedYetError`, thuộc Sprint 2-4.
- Docker/Caddy/API key store/rate limit — Sprint 5.

### Tiếp theo (đề xuất)
1. Chạy nốt Sprint 0 thật trên máy có LAN — xác nhận/sửa các giả định ở
   `config.py` (`dspace_solr_search_core`, `dspace_solr_fulltext_field`) và
   `mapping.py` (`ANONYMOUS_GROUP_ID`, hình dạng JSON policy).
2. Sprint 2: Solr client + `search_library` (metadata/fulltext/both) + `library_stats`.
