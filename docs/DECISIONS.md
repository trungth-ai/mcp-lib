# DECISIONS.md — Quyết định kiến trúc/implementation

Quyết định **sản phẩm/kiến trúc lớn** đã chốt với anh Trung: xem [README.md](../README.md)
mục "Quyết định đã chốt" và [05-security.md](../05-security.md). File này ghi các quyết
định **mức implementation** phát sinh khi code Sprint 1, chưa có trong bộ tài liệu gốc.

## 2026-07-02 — Sprint 1

### `allowed_levels` là tham số optional xuyên suốt interface, mặc định `None` = không lọc
**Vì sao**: 02-architecture.md nói "phân quyền là bất biến ở mọi đường ra dữ liệu", nhưng
07-sprints.md xếp việc lọc theo scope key vào Sprint 4 (chưa có bảng `api_keys`/auth ở
Sprint 1). Giải pháp: đưa `allowed_levels: tuple[AccessLevel,...] | None` vào chữ ký mọi
method của `ResourceProvider` NGAY TỪ Sprint 1, nhưng để `None` (không lọc) là mặc định.
Sprint 4 chỉ cần thêm middleware resolve scope→allowed_levels và truyền vào, KHÔNG phải
đổi interface hay sửa lại các provider đã viết.
**Hệ quả cần nhớ**: server.py hiện KHÔNG truyền allowed_levels cho tool nào — nghĩa là
Sprint 1 build ra **chưa an toàn để expose ra ngoài**, chỉ dùng nội bộ/dev.

### `access_level` mặc định `restricted` bất cứ khi nào không lấy được resource policy
Áp dụng cả khi API lấy policy lỗi (network, 404, ...) — không chỉ khi policy rỗng.
Đây là fail-safe bắt buộc theo NFR-1/05-security.md §3, ưu tiên "an toàn nhưng thiếu sót"
hơn "đầy đủ nhưng có thể lộ". Cân nhắc lại nếu sau này thấy quá nhiều item public bị
hiện restricted oan (dấu hiệu policy API không ổn định, không phải do chính sách thật).

### `get_recent_items`: over-fetch + sort phía client, chỉ fetch policy cho top-N sau khi sort
DSpace REST 6.x không có tham số sort theo ngày accession đáng tin cậy. Thay vì gọi
policy cho toàn bộ tập over-fetch (tốn N+1 request lớn), chỉ gọi policy cho đúng `limit`
item sau khi đã sort — chi phí phụ trội bị chặn trên bởi `limit`, không phải `fetch_n`.
**Giới hạn đã biết**: nếu các item "mới nhất" thật sự nằm ngoài `fetch_n` (mặc định
`min(max(limit*5, 50), 200)`), chúng sẽ bị bỏ sót. Chấp nhận được cho Sprint 1; nên thay
bằng Solr sort khi Sprint 2 xác nhận full-text/sort đã index (xem PLAN.md).

### Bitstream không có policy riêng → kế thừa `access_level` của item (không phải "public" mặc định)
`mapping.map_item_to_resource`: nếu không truyền `bitstream_policies` cho 1 bitstream cụ
thể, nó nhận đúng `access_level` đã suy ra của item (không tự ý coi là công khai hơn item
cha) — nhất quán với fail-safe, và khớp thực tế đa số bitstream ORIGINAL kế thừa quyền
đọc từ item chứa nó.

### Chỉ giữ bitstream bundle `ORIGINAL` trong `Resource.files`
Bỏ qua `LICENSE`, `TEXT` (OCR nội bộ), `THUMBNAIL` — không phải nội dung người dùng cần
tải. Nếu sau này cần trả cả bundle `TEXT` (vd cho pipeline Tầng 2/3 bóc text), nên tách
hàm map riêng thay vì nới điều kiện lọc này (tránh rò rỉ file phụ ra `get_item`/`search`).

## 2026-07-02 — Sprint 2

### Thiết kế lai: Solr chỉ tìm/lọc/rank, REST cung cấp metadata + access_level
**Vì sao**: khác REST API (cố định trong code Java DSpace, tôi nắm chắc hình dạng JSON),
schema Solr Discovery **tùy biến theo `discovery.xml` riêng từng site** — tôi không đủ
tin cậy để đoán đúng tên field Dublin Core trong Solr (vd field nào chứa `dc.title`,
định dạng `dc.date.issued_year` hay khác). Quyết định: Solr chỉ cần trả về đúng
**handle** của item khớp truy vấn (+ điểm/snippet); metadata thật và `access_level` lấy
lại qua `provider.get()` (REST, đã có từ Sprint 1, đáng tin hơn). Đánh đổi: mỗi trang kết
quả (mặc định 10) tốn thêm tối đa 10 cặp request REST (item + policy), chạy song song
(`asyncio.gather`) để giảm độ trễ. Thu lại được: tự động có `access_level` chính xác +
hậu kiểm quyền đúng yêu cầu 05-security.md §3, không cần đoán field metadata Solr.
**Hệ quả**: nếu field Solr `handle` (config `dspace_solr_field_handle`) sai tên, toàn bộ
search trả rỗng dù Solr có match — ưu tiên "rỗng nhưng an toàn" hơn "đoán bừa".

### Ghép highlight theo VỊ TRÍ, không theo key của `highlighting` dict
Solr trả `highlighting` là dict keyed theo `uniqueKey` của document — định dạng
`uniqueKey` thật của core `search` (thường dạng `"<resourcetype>-<uuid>"`) chưa xác
minh. Thay vì đoán, ghép `highlighting.values()` với `docs` theo đúng vị trí (index),
và CHỈ tin khi số lượng 2 bên khớp nhau (`len(highlighting) == len(docs)`) — lệch thì bỏ
toàn bộ highlight (rỗng), không suy đoán. An toàn vì ghép sai vị trí chỉ ảnh hưởng hiển
thị đoạn trích, không ảnh hưởng phân quyền (access_level luôn tính lại qua REST, độc lập
với dữ liệu Solr).

### `total` trong `search_library` là `numFound` thô của Solr, CHƯA trừ item bị lọc quyền
Vì lọc quyền xảy ra SAU khi Solr trả trang kết quả (qua REST, per-item), tính `total`
chính xác sau lọc sẽ cần quét toàn bộ tập match (phá vỡ phân trang/hiệu năng). Chấp nhận
`total` hơi cao hơn số kết quả `partner` thực sự thấy được — không phải rò rỉ thông tin
nội dung (chỉ lệch con số đếm), nhưng cần ghi trong tài liệu bàn giao đối tác sau này.

### `library_stats` KHÔNG lọc theo `allowed_levels` — ĐÃ SỬA ở Sprint 4, xem mục bên dưới
~~Khác `search_library`..., để trống lọc ở Sprint 2, xử lý đầy đủ ở Sprint 4~~ — 06-test-plan
§2.4 (điều kiện chặn merge) yêu cầu partner không thấy số liệu internal/restricted ngay
cả ở stats, nên đã cài lọc ở Sprint 4 thay vì để hoàn toàn tới Sprint 5 như dự tính ban
đầu. Chi tiết ở mục "`library_stats` lọc cho partner qua field `read`" (Sprint 4).

### `ANONYMOUS_GROUP_ID = 0` là giả định, đặt hằng số riêng dễ sửa
Group Anonymous trong DSpace theo tài liệu cộng đồng thường có id well-known `0`, nhưng
**chưa xác minh trên instance HPU thật** (Sprint 0 chưa chạy được — xem PLAN.md). Đặt
thành hằng số ở đầu `mapping.py` thay vì rải trong logic để 1 dòng sửa là xong khi có
số liệu thật.

## 2026-07-02 — Sprint 3

### Hình dạng REST API Gemini embedding: đã xác minh qua WebFetch, KHÔNG đoán
Khác field Solr/DSpace (nội bộ HPU, không tra cứu được), API Gemini embedding là tài
liệu công khai của Google — dùng WebFetch đọc `ai.google.dev/api/embeddings` +
`github.com/google-gemini/cookbook` (2 nguồn độc lập) trước khi viết `gemini_embedding.py`,
xác nhận: endpoint `POST .../models/{model}:batchEmbedContents`, header `x-goog-api-key`,
body **snake_case phẳng** (`model`, `content`, `output_dimensionality`, `task_type` — KHÔNG
lồng trong object `embedContentConfig` như 1 nguồn ban đầu gợi ý sai). `task_type` dùng
`RETRIEVAL_DOCUMENT` lúc ingest, `RETRIEVAL_QUERY` lúc `semantic_search` — đúng khuyến
nghị của Google để tối ưu chất lượng truy hồi bất đối xứng (query ngắn vs document dài).

### Chunker: đơn vị `size`/`overlap` là SỐ KÝ TỰ, không phải token
Đơn giản, không phụ thuộc tokenizer cụ thể của Gemini (chưa công khai đầy đủ). Cắt theo
ranh giới từ (space) sau khi chuẩn hóa Unicode NFC — không bao giờ cắt giữa 1 "từ" nên
không thể vỡ tổ hợp dấu tiếng Việt dù input ở dạng NFD (test `test_split_normalizes_unicode_nfc`).
Nếu sau này cần cắt theo token thật (khớp chi phí Gemini tính theo token), thêm 1
Chunker khác implement cùng chữ ký `split_text`, không sửa cái này.

### `VectorStore` dùng asyncpg thuần (raw SQL), không dùng SQLAlchemy/ORM
04-data-model.md đã cho sẵn SQL chính xác (kể cả toán tử `<=>` của pgvector) — bám nguyên
văn SQL đó thay vì dịch sang ORM giảm rủi ro dịch sai cú pháp vector-đặc-thù, và tránh
thêm dependency lớn cho 2 bảng (`doc_chunks`/`sync_state`). `db-conventions.md` (quy ước
chung HPU) ưu tiên SQLAlchemy cho app CRUD thông thường — đây là ngoại lệ có chủ đích vì
workload là vector search, không phải CRUD.

### `filters` (collection/year_from/type) của `semantic_search_documents` CHƯA áp dụng
SQL semantic trong 04-data-model.md chỉ lọc `access_level`, không có filter theo metadata.
Có thể mở rộng bằng cách lưu `collection`/`type`/`year` vào cột `meta JSONB` lúc ingest rồi
thêm điều kiện `meta->>'...' = $N`, nhưng đó là quyết định schema mới ngoài những gì tài
liệu gốc đã chốt — để ngỏ, ghi rõ trong docs/PLAN.md thay vì tự ý mở rộng schema.

### Pipeline `ingest.py`: quét lại `batch_limit` item mỗi lượt, không thật sự "tăng dần"
DSpace REST 6.x không có filter "đổi từ ngày X" đáng tin cậy (giống lý do `get_recent_items`
phải over-fetch ở Sprint 1). Idempotent qua `ON CONFLICT` nên chạy lại an toàn — đánh đổi
là tốn thêm request/chi phí embedding trùng lặp mỗi lần chạy. Nên thay bằng Solr sort theo
ngày khi Sprint 0 xác nhận field ngày thật (ghi trong docs/PLAN.md mục "Tiếp theo").

## 2026-07-02 — Sprint 4

### Quy tắc auth theo TRANSPORT, không dùng cờ bật/tắt kiểu `AUTH_MODE`
Thiết kế ban đầu có cân nhắc thêm `Settings.auth_mode: enforced|dev_open`, nhưng sau khi
đọc trực tiếp mã nguồn gói `mcp` đã cài (`Context.request_context.request` là
`starlette.Request | None` — `None` khi chạy stdio, có giá trị khi streamable-http) thấy
quy tắc có thể CỐ ĐỊNH theo transport mà không cần cờ: stdio/gọi trực tiếp = tin cậy cục
bộ (khớp bảng actor 01-requirements.md — Trung dùng Claude Code stdio); streamable-http =
LUÔN bắt buộc `Authorization: Bearer`. Bỏ cờ giảm 1 cấu hình có thể bị set sai khi deploy
(vd quên đổi `dev_open` → `enforced` trước khi expose ra Internet).

### `allowed_levels` truyền qua contextvar (`current_allowed_levels()`), không qua tham số hàm tool
Provider interface đã có sẵn `allowed_levels` từ Sprint 1, nhưng FastMCP tự sinh JSON
schema từ chữ ký hàm tool — nếu thêm `allowed_levels` làm tham số thường, nó sẽ LỘ RA cho
LLM client tự set (client có thể tự xưng "internal"!). Giải pháp: tái dùng contextvar đã
có sẵn cho log (`logging_setup._key_id_var`...), thêm `_allowed_levels_var` cùng cơ chế —
`_handle_errors` (server.py) resolve xong rồi set qua `tool_call_context(...)`, hàm tool
đọc lại bằng `current_allowed_levels()`. Không tool nào có thể tự khai báo quyền của mình.

### `ctx: Context | None = None` — cho phép gọi tool trực tiếp không qua FastMCP (test/script)
`ctx=None` được coi như stdio (client nội bộ tin cậy). Quyết định có chủ đích để: (1) test
gọi thẳng hàm tool mà không phải dựng `Context` thật của SDK (phụ thuộc session/transport
nội bộ, dễ vỡ khi SDK đổi version); (2) script vận hành nội bộ (vd cron dọn dẹp) gọi thẳng
logic tool mà không cần giả lập HTTP request. Test bảo mật (`test_security_matrix.py`)
dùng `FakeContext` duck-type đúng `ctx.request_context.request.headers` thay vì `ctx=None`
để mô phỏng CHÍNH XÁC luồng streamable-http thật (không bỏ qua bước resolve identity).

### `library_stats` lọc cho partner qua Solr field `read` (token `g0`), không qua REST hậu kiểm
Khác `search_library` (danh sách item hữu hạn, hậu kiểm từng cái qua REST khả thi),
`library_stats` là facet COUNT trên có thể hàng nghìn item — hậu kiểm per-item không khả
thi. Dùng thẳng field `read` mà DSpace tự index (cơ chế lõi `SolrServiceImpl`, KHÔNG tùy
biến qua `discovery.xml` — khác các field metadata khác), lọc `fq=read:g0` khi
`allowed_levels == {"public"}` đúng. Chỉ áp dụng cho trường hợp partner (public-only); scope
"internal" (thấy cả 3 mức) không thêm filter. **Chưa xác minh** token `g0` đúng định dạng
thật trên instance HPU (cùng mức tin cậy như `ANONYMOUS_GROUP_ID`).

### `get_document_text`/`find_in_document`: 2 tool, dùng chung 1 method provider
03-tools-spec.md liệt kê 2 tên tool trong cùng 1 mục nhưng chung I/O — thay vì đoán ý định
tài liệu, expose CẢ HAI tên tool (khớp đúng những gì LLM client có thể tra cứu theo tên),
cả 2 gọi `provider.get_text(id, query=..., page=...)` giống hệt nhau. `find_in_document`
không có `query` optional (bắt buộc) vì bản chất là "tìm", còn `get_document_text` để
`query=None` cho đúng nghĩa "lấy toàn bộ".

### Rate limit trong bộ nhớ (không dùng Redis) ở Sprint 4
"(nền)" theo 07-sprints.md nghĩa là baseline, chưa phải trọng tâm. Sliding window đơn giản
đủ cho 1 instance (giai đoạn hiện tại: 1 container theo 02-architecture.md). Khi Sprint 5+
scale ngang nhiều replica, giới hạn per-instance không còn đúng theo key toàn cục — cần
store dùng chung (Redis/Postgres) trước khi scale, KHÔNG âm thầm coi giới hạn hiện tại là
đủ cho production nhiều replica.
