# 04 — Mô hình dữ liệu (Data Model)

## 1. Schema tài nguyên chuẩn hóa (dùng chung mọi nguồn)

```json
{
  "id": "123456789/42",
  "source": "dspace",
  "title": "Ứng dụng học máy trong dự báo tuyển sinh",
  "authors": ["Nguyễn Văn A", "Trần Thị B"],
  "year": 2023,
  "type": "Thesis",
  "language": "vi",
  "abstract": "…",
  "collection": "Luận văn Thạc sĩ",
  "community": "Khoa CNTT",
  "url": "https://lib.hpu.edu.vn/handle/123456789/42",
  "access_level": "public",
  "files": [
    {
      "bitstream_id": "…",
      "name": "toanvan.pdf",
      "mime": "application/pdf",
      "size": 2451234,
      "bitstream_link": "https://lib.hpu.edu.vn/rest/bitstreams/…/retrieve",
      "access_level": "restricted"
    }
  ],
  "raw_meta": { "dc.contributor.advisor": "…", "...": "..." }
}
```

- `access_level` ∈ `public | internal | restricted` (xem [05-security.md](05-security.md)).
- `raw_meta` giữ nguyên metadata gốc để không mất thông tin khi chuẩn hóa.
- Nguồn mới (văn bản pháp quy…) map dữ liệu của nó về đúng schema này.

### Ánh xạ Dublin Core → schema (DSpace)
| Chuẩn hóa | DSpace metadata |
|---|---|
| title | `dc.title` |
| authors | `dc.contributor.author` |
| year | `dc.date.issued` (lấy năm) |
| type | `dc.type` |
| language | `dc.language.iso` |
| abstract | `dc.description.abstract` |

> Tên field Solr cho các mục trên (và **field full-text**, giả định `fulltext`) sẽ được
> xác nhận bằng dump schema ở Sprint 0 — không hardcode khi chưa verify.

## 2. Schema PostgreSQL + pgvector (Tầng 3)

```sql
CREATE EXTENSION IF NOT EXISTS vector;

-- Bảng chunk + embedding
CREATE TABLE doc_chunks (
    id            BIGSERIAL PRIMARY KEY,
    source        TEXT        NOT NULL,          -- 'dspace', ...
    item_id       TEXT        NOT NULL,          -- handle/uuid item
    chunk_index   INT         NOT NULL,
    content       TEXT        NOT NULL,
    embedding     vector(1536) NOT NULL,          -- Gemini gemini-embedding-001
    access_level  TEXT        NOT NULL DEFAULT 'public',  -- public|internal|restricted
    page          INT,
    title         TEXT,
    url           TEXT,
    meta          JSONB,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, item_id, chunk_index)
);

-- Chỉ mục vector (HNSW cho chất lượng tìm kiếm)
CREATE INDEX idx_doc_chunks_embedding
    ON doc_chunks USING hnsw (embedding vector_cosine_ops);

-- Lọc nhanh theo quyền & nguồn
CREATE INDEX idx_doc_chunks_access ON doc_chunks (source, access_level);

-- Theo dõi đồng bộ tăng dần
CREATE TABLE sync_state (
    source          TEXT PRIMARY KEY,
    last_synced_at  TIMESTAMPTZ,
    last_item_ts    TIMESTAMPTZ,
    notes           TEXT
);
```

**Truy vấn semantic (đã kèm lọc quyền):**
```sql
SELECT item_id, chunk_index, content, title, url, page,
       1 - (embedding <=> $1) AS score
FROM doc_chunks
WHERE source = $2
  AND access_level = ANY($3)      -- danh sách mức key được phép
ORDER BY embedding <=> $1
LIMIT $4;
```

> `vector(1536)` cố ý khớp cấu hình RAG hiện tại của HPU (`gemini-embedding-001`, 1536 chiều)
> để hai hệ dùng chung không lệch số chiều. Nếu sau này đổi embedding khác số chiều → thêm
> cột/bảng mới theo model, không phá dữ liệu cũ.

## 3. Bảng quản trị API key (tóm tắt — chi tiết ở 05)
```sql
CREATE TABLE api_keys (
    id          TEXT PRIMARY KEY,        -- key-id (không lưu key thô)
    key_hash    TEXT NOT NULL,           -- hash của key
    label       TEXT,                    -- 'RAG chatbot', 'Đối tác X'
    scope       TEXT NOT NULL,           -- 'internal' | 'partner'
    rate_limit  INT,
    active      BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ DEFAULT now()
);
```
