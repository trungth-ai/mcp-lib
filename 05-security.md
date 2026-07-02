# 05 — Bảo mật (Security Model)

## 1. Mô hình mối đe dọa (rút gọn)
- MCP giữ **service account đặc quyền** đọc được tài liệu hạn chế.
- MCP **mở ra ngoài** cho đối tác qua API key.
- ⇒ Rủi ro lõi: **đối tác ngoài moi ra tài liệu hạn chế**. Đây là điều phải chặn tuyệt đối
  (đặc biệt khi trường đang có yếu tố pháp lý nhạy cảm và dữ liệu 24k cựu SV).

## 2. Xác thực client
- Mỗi client dùng **API key** (bearer). Key không lưu thô; lưu `key_hash` + `key-id` + `scope`.
- 2 scope: **`internal`** (RAG, agent tuyển sinh, Claude Code, AI Lab) và **`partner`** (đối tác ngoài).
- Thu hồi/tạm khóa từng key độc lập (`active=false`).
- Rate limit theo key.

## 3. Phân tầng quyền (bất biến của hệ thống)

Ánh xạ scope → mức truy cập được phép:

| scope key | access_level được thấy |
|---|---|
| `partner` | `public` |
| `internal` | `public`, `internal`, `restricted` |

Quy tắc thực thi:
- **Lọc tại nguồn ra dữ liệu**, không lọc ở client. Mọi tool (search, semantic, get_item,
  get_document_text, get_bitstream_link, stats…) tính `allowed_levels` từ scope key rồi mới truy vấn.
- Search Solr: thêm điều kiện lọc theo trường quyền của item; nếu Solr không đủ tin cậy để lọc,
  **hậu kiểm** từng kết quả qua chính sách đọc của item (REST) trước khi trả.
- Semantic (pgvector): `WHERE access_level = ANY(allowed_levels)`.
- get_document_text / bitstream: kiểm `access_level` tài liệu trước khi bóc/trả; thiếu quyền → `forbidden`.
- **Nguyên tắc mặc định**: khi chưa xác định được mức truy cập của một tài liệu → coi là
  `restricted` (fail-safe), không mặc định public.

## 4. Xác định `access_level` của tài liệu
- Suy ra từ **chính sách đọc (resource policy)** của item/bitstream trong DSpace:
  - Anonymous READ ⇒ `public`.
  - READ giới hạn nhóm nội bộ ⇒ `internal`.
  - Không có READ cho anonymous / có embargo ⇒ `restricted`.
- Với Tầng 3: gán `access_level` cho chunk **ngay lúc ingest** (đóng băng theo policy tại thời điểm đó),
  và **đồng bộ lại khi policy đổi** (job kiểm định kỳ). Item chuyển sang hạn chế ⇒ cập nhật/gỡ chunk.

## 5. Quản lý bí mật (service account, khóa)
- Credential service account & API keys nạp qua **Docker secret / biến môi trường**, không nằm trong image, không commit repo.
- Token đăng nhập DSpace giữ trong bộ nhớ tiến trình, tự refresh, **không ghi log**.
- Log áp **redaction**: che key, token, mật khẩu.

## 6. Audit & quan trắc
- Mỗi request log: thời gian, `request-id`, `key-id`, `scope`, tool, tham số rút gọn, số kết quả, độ trễ.
- **Audit riêng** cho mọi lần truy cập tài liệu `internal`/`restricted`: key-id + item-id + kết quả (cho/từ chối).
- Cảnh báo khi: key `partner` bị từ chối truy cập hạn chế nhiều lần bất thường; tỉ lệ lỗi tăng; độ trễ vượt ngưỡng.

## 7. Mạng
- MCP ↔ Solr/REST đi trong LAN (`10.1.0.0/27`), không qua Internet.
- Bề mặt public duy nhất là endpoint MCP qua Caddy (`mcp-lib.hpu.edu.vn`), có TLS + key + rate limit.
- Chặn Solr public do anh Trung xử lý ở Traefik (ngoài phạm vi, nhưng là tiền đề an toàn).

## 8. Bất biến phải có test (xem 06)
1. Key `partner` **không bao giờ** nhận nội dung/không metadata của tài liệu `internal`/`restricted` — ở **mọi** tool.
2. Tài liệu chưa xác định mức truy cập → xử như `restricted`.
3. Không có token/credential nào lọt vào log.
