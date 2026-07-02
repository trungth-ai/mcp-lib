# 07 — Kế hoạch Sprint

Mỗi sprint là một **chunk được duyệt** rồi mới làm. Ước lượng theo tuần công.
Cột "GĐ" đánh dấu việc dành cho DSpace **6.3** hay chờ **v10**.

| Sprint | Tên | Ước lượng |
|---|---|---|
| 0 | Trinh sát & xác minh | 0.5 tuần |
| 1 | Lõi MCP + Provider + tools metadata | 1 tuần |
| 2 | Solr search + full-text Tầng 1 | 1 tuần |
| 3 | Ngữ nghĩa Tầng 3 (pgvector) | 1–1.5 tuần |
| 4 | Bóc text Tầng 2 + phân tầng quyền | 1 tuần |
| 5 | Đóng gói Docker + Caddy + API key | 0.5–1 tuần |
| 6 | Tích hợp RAG/agent + SKILL.md + tài liệu | 0.5 tuần |
| Sau | DSpace10Adapter | khi lên v10 |

**Tổng GĐ1: ~5.5–6.5 tuần.**

---

## Sprint 0 — Trinh sát & xác minh
**Mục tiêu**: biến các "giả định" thành "sự thật" trước khi code.

Đầu việc & lệnh kiểm chứng (chạy trên/■từ host phù hợp):
- REST 6.3 còn sống? `curl http://10.1.0.205:8088/rest/communities` (hoặc cổng REST thật) → JSON.
- Liệt kê Solr core: `curl "http://10.1.0.205:8088/solr/admin/cores?action=STATUS&wt=json"`.
- **Full-text đã index chưa** (quyết định Tầng 1):
  `curl "http://10.1.0.205:8088/solr/search/select?q=fulltext:*&rows=0&wt=json"`
  → `numFound > 0` là có; `0` hoặc lỗi field → chưa index / khác tên field.
- Dump schema field: `curl "http://10.1.0.205:8088/solr/search/schema/fields?wt=json"`.
- Thử **service account**: `POST /rest/login` (email+password) → nhận token; thử `GET` một item hạn chế để xác nhận quyền đọc.
- Kiểm analyzer tiếng Việt: query "tuyen sinh" vs "tuyển sinh" xem kết quả.

**Nghiệm thu**: có bảng "sự thật xác minh" (tên core, tên field full-text, full-text có/không, quyền service account, hành vi tiếng Việt). Nếu full-text **chưa** index → ghi rõ khuyến nghị bật `filter-media` + `index-discovery` cho anh Trung (việc phía DSpace).

---

## Sprint 1 — Lõi MCP + Provider + tools metadata  · GĐ 6.3
- Khung FastMCP: config, logging (có redaction), error handling, health.
- Interface `ResourceProvider` + registry; `DSpaceProvider` + `DSpace6Adapter` (login, get item, list communities/collections, bitstream link).
- Tools: `get_item`, `list_communities`, `list_collections`, `get_recent_items`, `get_bitstream_link`.
- Chạy `stdio`, test trên Claude Code/Desktop.
- Unit: chuẩn hóa metadata, adapter parse, lỗi mạng.

**Phụ thuộc**: Sprint 0.
**Nghiệm thu**: từ Claude Code gọi được các tool metadata, trả schema đúng [03](03-tools-spec.md); unit xanh.

---

## Sprint 2 — Solr search + full-text Tầng 1  · GĐ 6.3
- Solr client (gọi LAN nội bộ), `search_library` (scope metadata/fulltext/both, filter, facet, phân trang).
- Bật **highlight** cho full-text; chuẩn hóa snippet.
- `library_stats` qua facet.
- Test tiếng Việt (có/không dấu); test suy biến khi full-text trống.

**Phụ thuộc**: Sprint 1; kết quả full-text ở Sprint 0.
**Nghiệm thu**: tìm được theo nội dung + trả highlight; facet đúng; test tiếng Việt xanh.

---

## Sprint 3 — Ngữ nghĩa Tầng 3 (pgvector)  · GĐ 6.3
- Postgres + pgvector (container); schema `doc_chunks` + `sync_state` (vector **1536d**).
- `EmbeddingProvider` (Gemini) sau interface; `Chunker` cấu hình được; `VectorStore`.
- Pipeline ingest có điều tiết + đồng bộ tăng dần theo `lastModified`; gán `access_level` lúc ingest.
- Tool `semantic_search_documents` (kèm lọc `access_level`).
- Đo chi phí embedding; upsert idempotent.

**Phụ thuộc**: Sprint 1 (+ text từ Sprint 2/Tầng 2).
**Nghiệm thu**: ingest tập mẫu → semantic trả đúng tài liệu liên quan + trích dẫn; đồng bộ tăng dần chạy lại không nhân đôi chunk.

---

## Sprint 4 — Bóc text Tầng 2 + phân tầng quyền  · GĐ 6.3
- `get_document_text` / `find_in_document`: tải bitstream (kể cả hạn chế) bằng service account, bóc text (Tika/pdfplumber), trả trang/đoạn.
- Suy diễn `access_level` từ resource policy; **mặc định restricted khi mơ hồ**.
- Áp **phân tầng quyền theo scope key** cho *mọi* tool (search, semantic, get, stats).
- Bảng `api_keys` + kiểm key + rate limit (nền).
- **Test phân quyền đầy đủ** (mục 06.2.4) — điều kiện chặn merge.

**Phụ thuộc**: Sprint 1–3.
**Nghiệm thu**: 100% test phân quyền xanh; key `partner` không chạm được tài liệu hạn chế ở bất kỳ đâu.

---

## Sprint 5 — Đóng gói & phục vụ  · GĐ 6.3
- Dockerfile + docker-compose (MCP + Postgres/pgvector).
- Streamable HTTP; Caddy `mcp-lib.hpu.edu.vn` (TLS, DNS `27.72.202.13`).
- API key theo client + rate limit + audit; secret qua Docker secret/env.
- Health/metrics; hướng dẫn rotate key & chạy lại đồng bộ.

**Phụ thuộc**: Sprint 4.
**Nghiệm thu**: client ngoài gọi qua HTTPS bằng key; key sai/hết hạn bị chặn; audit ghi truy cập hạn chế.

---

## Sprint 6 — Tích hợp & bàn giao  · GĐ 6.3
- Cắm MCP vào RAG `chat.hpu.edu.vn`, agent tuyển sinh, Claude Code.
- Viết `SKILL.md` theo hpu-dev v2.0; tài liệu cho AI Lab + đối tác ngoài.
- Rà soát end-to-end; chốt Definition of Done (06.6).

**Nghiệm thu**: RAG trích dẫn được tài liệu thư viện qua MCP; tài liệu bàn giao đủ.

---

## Sau GĐ1 — DSpace10Adapter (khi lên v10)
- Hiện thực adapter REST mới `/server/api` (JWT), map về cùng interface.
- Chạy song song test hồi quy: đổi `DSPACE_VERSION` sang `v10`, toàn bộ tool giữ hành vi.
- Rà lại tên field/search discovery v10; cập nhật pipeline ngữ nghĩa nếu nguồn text đổi.

**Nghiệm thu**: chuyển 6.3 → v10 không phải sửa tool; test hồi quy xanh.

---

## Đường găng (critical path)
`Sprint 0 → 1 → (2 ∥ 3) → 4 → 5 → 6`. Sprint 2 và 3 có thể chạy song song một phần
sau khi Sprint 1 xong (cùng dựa trên Provider). Sprint 4 gom quyền nên phải sau 2 & 3.
