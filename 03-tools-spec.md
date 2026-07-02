# 03 — Đặc tả Tools (MCP Tools Spec)

Quy ước chung:
- Mọi tool nhận `source` (mặc định `"dspace"`) để định tuyến nguồn.
- Mọi tool **lọc theo `access_level`** cho phép của API key trước khi trả (xem [05-security.md](05-security.md)).
- Mọi output kèm `citations` để LLM trích dẫn (nguồn, id, url).
- Lỗi trả cấu trúc `{ "error": { "code", "message" } }`, không lộ chi tiết nội bộ.

---

## `search_library`
Tìm theo từ khóa (metadata và/hoặc nội dung), có facet, phân trang, highlight.

**Input**
```json
{
  "query": "string",
  "source": "dspace",
  "scope": "metadata | fulltext | both",
  "filters": {
    "collection": "string?",
    "community": "string?",
    "year_from": "int?",
    "year_to": "int?",
    "type": "string?",
    "author": "string?"
  },
  "facets": ["type", "year", "author"],
  "page": 1,
  "page_size": 10
}
```
**Output**
```json
{
  "total": 128,
  "page": 1,
  "page_size": 10,
  "results": [
    {
      "id": "123456789/42",
      "source": "dspace",
      "title": "…",
      "authors": ["…"],
      "year": 2023,
      "type": "Thesis",
      "collection": "Luận văn Thạc sĩ",
      "url": "https://lib.hpu.edu.vn/handle/123456789/42",
      "highlights": ["…đoạn có <em>từ khóa</em>…"],
      "access_level": "public"
    }
  ],
  "facets": { "type": {"Thesis": 40}, "year": {"2023": 12} },
  "citations": [ {"id": "123456789/42", "url": "…"} ]
}
```
`highlights` chỉ có khi `scope` gồm `fulltext` và Solr đã index full-text.

---

## `semantic_search_documents`
Tìm theo ý nghĩa trên chunk đã embed (Tầng 3).

**Input**
```json
{
  "query": "string",
  "source": "dspace",
  "k": 8,
  "filters": { "collection": "string?", "year_from": "int?", "type": "string?" }
}
```
**Output**
```json
{
  "chunks": [
    {
      "item_id": "123456789/42",
      "chunk_index": 7,
      "text": "…đoạn nội dung liên quan…",
      "score": 0.83,
      "title": "…",
      "url": "https://lib.hpu.edu.vn/handle/123456789/42",
      "page": 5,
      "access_level": "public"
    }
  ],
  "citations": [ {"id": "123456789/42", "url": "…", "page": 5} ]
}
```

---

## `get_item`
Metadata Dublin Core chuẩn hóa + danh sách bitstream.

**Input**
```json
{ "id": "123456789/42", "source": "dspace" }
```
**Output**: đối tượng `Resource` (xem [04-data-model.md](04-data-model.md)) gồm `files[]`
(mỗi file có `name`, `mime`, `size`, `bitstream_link`, `access_level`).

---

## `get_document_text` / `find_in_document`
Bóc & trả nội dung tài liệu (Tầng 2, có xác thực). `find_in_document` trả các đoạn khớp.

**Input**
```json
{ "id": "123456789/42", "query": "string?", "page": "int?", "source": "dspace" }
```
**Output**
```json
{
  "id": "123456789/42",
  "pages": [ { "page": 5, "text": "…", "matches": ["…"] } ],
  "truncated": false,
  "access_level": "restricted"
}
```
> Nếu key không đủ quyền với `access_level` của tài liệu → trả lỗi `forbidden`, **không**
> trả nội dung, và ghi audit.

---

## `list_communities` / `list_collections`
Cây đơn vị / danh mục bộ sưu tập.
**Input**: `{ "parent": "string?", "source": "dspace" }`
**Output**: `{ "nodes": [ {"id","name","type","count"} ] }` (đã lọc theo quyền).

---

## `get_recent_items`
**Input**: `{ "collection": "string?", "limit": 10, "source": "dspace" }`
**Output**: danh sách `Resource` rút gọn, sắp theo ngày nạp.

---

## `get_bitstream_link`
**Input**: `{ "item_id": "…", "bitstream_id": "…", "source": "dspace" }`
**Output**: `{ "url": "…", "requires_auth": true|false, "access_level": "…" }`
> Với tài liệu hạn chế: chỉ trả link cho key nội bộ; key ngoài nhận `forbidden`.

---

## `library_stats`
**Input**: `{ "source": "dspace", "group_by": ["type","year","collection"] }`
**Output**: `{ "total_items": …, "by": { "type": {...}, "year": {...} } }`
Thống kê chỉ tính phần dữ liệu key được phép thấy.

---

## Bảng tóm tắt quyền theo scope key

| Tool | Key đối tác ngoài | Key nội bộ |
|---|---|---|
| search_library / semantic / recent / stats | chỉ `public` | tất cả mức |
| get_item / get_bitstream_link | chỉ item `public` | tất cả |
| get_document_text / find_in_document | chỉ `public` | gồm `internal`/`restricted` |
