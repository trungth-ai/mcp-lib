# secrets/ — trạng thái (không chứa giá trị thật trong file này)

File `*.txt` thật (không phải `.example`) đã bị `.gitignore`, không commit. Trạng thái
hiện tại trên máy dev này:

| File | Trạng thái |
|---|---|
| `postgres_password.txt` | Đã tự sinh (random, mạnh) — dùng được ngay cho Postgres local/Docker |
| `database_url.txt` | Đã tự sinh, khớp `postgres_password.txt`, host mặc định `postgres` (tên service trong `docker-compose.yml`) — **đổi thành `localhost` nếu chạy Postgres ngoài Docker** |
| `dev_static_api_key.txt` | Đã tự sinh (random, mạnh) — chỉ dùng dev/demo streamable-http khi CHƯA có `api_keys` thật trong Postgres (xem `admin_keys.py`) |
| `dspace_service_password.txt` | **CHƯA có — cần anh Trung điền mật khẩu service account DSpace thật**, không tự bịa được |
| `gemini_api_key.txt` | **CHƯA có — cần anh Trung điền API key Gemini thật**, không tự bịa được |

Thiếu 2 file cuối chỉ ảnh hưởng: DSpace REST sẽ chạy ở chế độ anonymous (chỉ đọc được
tài liệu public), và `semantic_search_documents`/`ingest.py` báo lỗi rõ ràng "chưa cấu
hình" thay vì hoạt động — không phải lỗi ngầm.

Xem [../docs/DEPLOY.md](../docs/DEPLOY.md) để biết cách dùng các file này khi build Docker.
