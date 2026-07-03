# DEPLOY.md — Vận hành (Sprint 5)

Áp dụng cho host MCP `10.1.0.207` (Ubuntu + Docker), theo 02-architecture.md §3.
**CHƯA chạy thử thật** (máy dev Windows không có Docker) — làm đúng theo tài liệu
Docker/Compose chuẩn, nhưng anh Trung nên chạy thử ở môi trường staging trước khi để
Caddy trỏ domain thật vào.

## 1. Chuẩn bị secrets (1 lần)

```bash
cp secrets/postgres_password.txt.example secrets/postgres_password.txt
cp secrets/database_url.txt.example secrets/database_url.txt
cp secrets/dspace_service_password.txt.example secrets/dspace_service_password.txt
cp secrets/gemini_api_key.txt.example secrets/gemini_api_key.txt
cp secrets/dev_static_api_key.txt.example secrets/dev_static_api_key.txt
# Sửa từng file bằng giá trị thật. secrets/*.txt đã bị .gitignore, không commit.
```

`secrets/database_url.txt` phải dùng ĐÚNG mật khẩu đã đặt trong `secrets/postgres_password.txt`
(2 file độc lập, Compose không tự đồng bộ hộ) — dạng:
`postgresql://hpu_library_mcp:<mật khẩu>@postgres:5432/hpu_library_mcp`.

**Quan trọng — thứ tự ưu tiên cấu hình của pydantic-settings**: biến môi trường/`.env`
được ưu tiên HƠN Docker secret. Nếu `.env` có dòng `GEMINI_API_KEY=` (kể cả để trống),
nó sẽ ĐÈ MẤT giá trị từ secret. Khi dùng Docker secrets, **xóa hẳn** (không chỉ để
trống) các dòng sau khỏi `.env` trên host: `DSPACE_SERVICE_PASSWORD`, `GEMINI_API_KEY`,
`DATABASE_URL`, `DEV_STATIC_API_KEY`. Các biến còn lại (URL DSpace, tên field Solr,
`MCP_*`...) vẫn để trong `.env` bình thường.

## 2. Build & chạy

```bash
cp .env.example .env   # điền URL DSpace/Solr thật + field đã xác nhận ở Sprint 0
docker compose build
docker compose up -d
docker compose logs -f mcp
```

Kiểm tra sống:
```bash
curl -s http://127.0.0.1:8800/health | jq .
```
`status: "ok"` nếu DSpace REST gọi được; `"degraded"` (HTTP 503) nếu không — container
vẫn được coi là "healthy" ở mức Docker (process còn sống), vì DSpace down là lỗi hạ
tầng ngoài, không phải MCP chết (xem HEALTHCHECK trong Dockerfile).

## 3. Cắm Caddy (trên host, ngoài Docker Compose)

```bash
sudo cp Caddyfile /etc/caddy/Caddyfile   # hoặc include vào Caddyfile chung của host
sudo systemctl reload caddy
```
Yêu cầu DNS `mcp-lib.hpu.edu.vn` → `27.72.202.13` đã trỏ đúng trước (Caddy tự xin TLS).

## 4. Tạo API key đầu tiên

```bash
docker compose exec mcp python -m hpu_library_mcp.admin_keys create \
    --label "RAG chatbot chat.hpu.edu.vn" --scope internal
# In ra KEY THÔ đúng 1 lần — chép lại ngay, đưa cho client qua kênh an toàn (không email/chat thường).
docker compose exec mcp python -m hpu_library_mcp.admin_keys list
```
Scope hợp lệ: `internal` (thấy public+internal+restricted) hoặc `partner` (chỉ public) —
xem 05-security.md §3.

## 5. Rotate (thu hồi) key

```bash
docker compose exec mcp python -m hpu_library_mcp.admin_keys revoke <key_id>
docker compose exec mcp python -m hpu_library_mcp.admin_keys create --label "..." --scope ...
```
Revoke là soft (`active=false`, không xóa hàng — đúng quy ước `db-conventions.md` không
hard delete). Đưa key mới cho client, yêu cầu client cập nhật, sau đó revoke key cũ.

## 6. Chạy lại đồng bộ embedding (Tầng 3)

```bash
docker compose exec mcp python -m hpu_library_mcp.ingest
```
Idempotent (upsert theo `source+item_id+chunk_index`) — chạy lại an toàn, không tạo
chunk trùng. Xem log `ingest_sync_done` để biết số item/chunk đã xử lý.

## 7. Sự cố thường gặp

| Triệu chứng | Nguyên nhân khả dĩ |
|---|---|
| `/health` báo `dspace.status: down` | LAN tới `10.1.0.205` bị chặn, hoặc REST 6.3 đổi cổng/tắt |
| `semantic_search_documents` báo `UPSTREAM_ERROR` "chưa cấu hình" | Thiếu `GEMINI_API_KEY` hoặc `DATABASE_URL` (kiểm `/health` → `semantic_search_configured`) |
| Mọi request qua Caddy đều `FORBIDDEN` dù key đúng | `DATABASE_URL` bị `.env` đè mất secret (xem mục 1) — kiểm `docker compose exec mcp env \| grep DATABASE_URL` |
| `search_library` trả rỗng dù chắc có dữ liệu | Tên field Solr trong `.env` sai — xem docs/DECISIONS.md, chạy lại Sprint 0 để xác nhận |
| Container `mcp` cứ khởi động rồi thoát code 0 lặp lại (log chỉ có `hpu_library_mcp_starting transport=stdio` rồi `exited with code 0`) | `.env` có `MCP_TRANSPORT=stdio` (mặc định của `.env.example`, dành cho chạy local trực tiếp) — stdio không chạy được trong container (không có stdin liên tục, thoát ngay). `docker-compose.yml` đã ép cứng `MCP_TRANSPORT=streamable-http` cho service `mcp` từ bản sửa này; nếu vẫn gặp, chạy `docker compose build` lại (compose cũ chưa có dòng ép cứng) |
