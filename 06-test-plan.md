# 06 — Kế hoạch Test (Test Plan)

## 1. Nguyên tắc
- **Test-first cho các bất biến bảo mật** (mục 4) — viết test trước khi code chức năng liên quan.
- Fixtures dùng **dữ liệu thật rút gọn** từ thư viện (một số item public + internal + restricted mẫu).
- Không phụ thuộc mạng LAN khi chạy unit: mock REST/Solr; integration mới gọi thật.
- Công cụ: `pytest`, `pytest-asyncio`, `respx`/`httpx-mock` (mock HTTP), `testcontainers-postgres` cho pgvector.

## 2. Kim tự tháp test

### 2.1 Unit (nhiều nhất)
- **Chuẩn hóa metadata**: DC → schema; thiếu field → không vỡ; nhiều tác giả; năm khuyết.
- **Adapter 6.3**: parse phản hồi `/rest`; xử lý item không có bitstream; lỗi 401/404/timeout.
- **Suy diễn `access_level`** từ resource policy: các tổ hợp anonymous/nhóm/embargo → đúng mức; **mặc định restricted khi mơ hồ**.
- **Bộ lọc quyền**: cho `allowed_levels` theo scope → truy vấn/kết quả chỉ chứa mức cho phép.
- **Chunker**: size/overlap đúng; không cắt vỡ Unicode tiếng Việt.
- **Vector layer**: build câu SQL semantic có kèm `access_level = ANY(...)`.
- **Redaction log**: token/key/mật khẩu bị che.

### 2.2 Integration
- **DSpace6Adapter thật** (môi trường test/LAN): login service account, list collections, get item, tải bitstream mẫu.
- **Solr full-text (Tầng 1)**: query có `hl=true`, nhận highlight; kiểm khi field full-text trống thì suy biến mượt (không lỗi).
- **pgvector (Tầng 3)**: ingest vài tài liệu mẫu → `semantic_search_documents` trả đúng tài liệu liên quan; upsert idempotent; gỡ chunk khi item bị ẩn.
- **MCP contract**: liệt kê tool, JSON schema I/O khớp [03-tools-spec.md](03-tools-spec.md); transport stdio & Streamable HTTP đều gọi được.

### 2.3 Test tiếng Việt (bắt buộc)
- Truy vấn **có dấu** và **không dấu** cùng trả kết quả (vd "tuyen sinh" ≈ "tuyển sinh").
- Ưu tiên đúng dấu xếp trên khi có.
- Tách từ hợp lý (không vỡ cụm "học máy", "trí tuệ nhân tạo").
- Highlight không cắt giữa ký tự tổ hợp dấu.

### 2.4 Test phân quyền (bảo mật — quan trọng nhất)
Cho từng tool trả dữ liệu, chạy với **key `partner`** và **key `internal`**:
- `partner` + item `restricted`/`internal` ⇒ **không** xuất hiện trong `search_library`, `semantic_search_documents`, `get_recent_items`, `library_stats`; `get_item`/`get_document_text`/`get_bitstream_link` ⇒ `forbidden` + ghi audit.
- `internal` ⇒ thấy đủ.
- Tài liệu **thiếu thông tin quyền** ⇒ đối xử `restricted`; `partner` không thấy.
- **Test rò rỉ**: quét log/lỗi/audit đảm bảo không lộ nội dung hay token.

### 2.5 Test hiệu năng & tải (nhẹ)
- Đo p95 search/semantic theo NFR-3 trên tập mẫu.
- Kiểm rate limit chặn đúng ngưỡng theo key.

## 3. Ma trận truy vết (test ↔ yêu cầu)

| Test | Bao phủ |
|---|---|
| Chuẩn hóa metadata | FR-1, FR-4 |
| Solr highlight | FR-2 |
| pgvector semantic | FR-3 |
| Bóc text có xác thực | FR-5 |
| Duyệt cây / recent / stats | FR-6 |
| Định tuyến `source` | FR-7 |
| Phân quyền mọi tool | FR-8, NFR-1, SEC-bất biến 1–2 |
| Redaction log | NFR-2, SEC-bất biến 3 |
| Test tiếng Việt | NFR-5 |
| Contract stdio/HTTP | NFR-4 |

## 4. Bất biến bảo mật (mọi build phải xanh)
1. Key `partner` **không bao giờ** nhận dữ liệu `internal`/`restricted` ở bất kỳ tool nào.
2. Tài liệu mơ hồ quyền ⇒ `restricted`.
3. Không token/credential nào trong log.

## 5. CI (đề xuất)
- Chạy unit + test phân quyền + test tiếng Việt trên mỗi commit.
- Integration + pgvector chạy theo nightly hoặc khi chạm adapter/tầng vector.
- **Chặn merge** nếu bất kỳ bất biến bảo mật nào đỏ.

## 6. Tiêu chí nghiệm thu tổng (Definition of Done — Giai đoạn 1)
- Toàn bộ test mục 2 xanh, đặc biệt 100% test phân quyền.
- Bộ tài liệu khớp code (schema tool đúng thực tế).
- Chạy được cả `stdio` (Claude Code) và Streamable HTTP (qua Caddy).
- Có hướng dẫn vận hành + rotate key + chạy lại đồng bộ embedding.
