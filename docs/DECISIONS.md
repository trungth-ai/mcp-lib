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

### `library_stats` KHÔNG lọc theo `allowed_levels`
Khác `search_library` (lọc per-item qua REST), `stats` chỉ đọc facet count tổng hợp từ
Solr — không có danh sách item để hậu kiểm từng cái. Lọc đúng cần biết ánh xạ
access_level ↔ DSpace group id thật để thêm `fq=read:...`, thứ chưa xác định (xem mục
`ANONYMOUS_GROUP_ID` bên dưới). Để trống lọc ở Sprint 2, xử lý đầy đủ ở Sprint 4 cùng lúc
với bảng `api_keys` — nhất quán với các method Sprint 1 khác (mặc định không lọc khi
`allowed_levels=None`).

### `ANONYMOUS_GROUP_ID = 0` là giả định, đặt hằng số riêng dễ sửa
Group Anonymous trong DSpace theo tài liệu cộng đồng thường có id well-known `0`, nhưng
**chưa xác minh trên instance HPU thật** (Sprint 0 chưa chạy được — xem PLAN.md). Đặt
thành hằng số ở đầu `mapping.py` thay vì rải trong logic để 1 dòng sửa là xong khi có
số liệu thật.
