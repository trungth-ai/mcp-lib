# 01 — Yêu cầu (Requirements)

## 1. Phạm vi

### Trong phạm vi (Giai đoạn 1)
- MCP Server **chỉ đọc** trên dữ liệu thư viện DSpace.
- Tìm kiếm metadata + facet + phân trang.
- **Tìm kiếm xuyên nội dung tài liệu** (3 tầng: full-text Solr, bóc text có xác thực, ngữ nghĩa pgvector).
- Truy xuất metadata chi tiết, link tải file, tài liệu mới nhất, thống kê.
- Xác thực client bằng **API key**, có **phân tầng quyền**.
- Triển khai Docker trên host Ubuntu, phục vụ qua Caddy tại `mcp-lib.hpu.edu.vn`.
- Kiến trúc **đa nguồn** (ResourceProvider) và **đa phiên bản DSpace** (adapter 6.3 / v10).

### Ngoài phạm vi (giai đoạn sau)
- Thao tác **ghi** (submit item, workflow, sửa metadata).
- Chặn Solr public / cấu hình Traefik (anh Trung tự xử lý).
- Nguồn phi-DSpace (văn bản pháp quy, CSDL khác) — chỉ *chuẩn bị chỗ cắm*, chưa hiện thực.
- Nâng cấp chất lượng RAG (reranker, hybrid search) — thiết kế sẵn đường mở, làm sau.

## 2. Đối tượng dùng (actors)

| Actor | Kênh | Mức quyền dự kiến |
|---|---|---|
| RAG chatbot `chat.hpu.edu.vn` | Streamable HTTP + key nội bộ | Nội bộ (rộng) |
| Agent tư vấn tuyển sinh | Streamable HTTP + key nội bộ | Nội bộ |
| Claude Code / Desktop của anh Trung | stdio hoặc HTTP + key nội bộ | Nội bộ |
| Đối tác ngoài | Streamable HTTP + key đối tác | Chỉ tài liệu công khai |
| Kỹ sư AI Lab | stdio (dev) | Nội bộ |

## 3. Yêu cầu chức năng (FR)

- **FR-1 Search metadata**: tìm theo từ khóa trên title/author/subject…, lọc theo collection/năm/loại, có facet, phân trang.
- **FR-2 Search full-text (Tầng 1)**: tìm trong nội dung đã bóc sẵn của Solr, trả **đoạn trích highlight** kèm vị trí.
- **FR-3 Semantic search (Tầng 3)**: tìm theo *ý nghĩa* trên chunk đã embed, trả chunk + điểm tương đồng + trích dẫn nguồn.
- **FR-4 Get item**: trả metadata Dublin Core chuẩn hóa + danh sách bitstream + link.
- **FR-5 Document text (Tầng 2)**: bóc & trả nội dung/đoạn của một tài liệu cụ thể (có xác thực, tôn trọng phân quyền).
- **FR-6 Duyệt cây**: list communities / collections; recent items; library stats.
- **FR-7 Định tuyến nguồn**: mọi tool nhận tham số `source` (mặc định `dspace`).
- **FR-8 Phân quyền kết quả**: mọi tool lọc kết quả theo mức quyền của API key trước khi trả.

## 4. Yêu cầu phi chức năng (NFR)

- **NFR-1 Bảo mật**: key đối tác **không bao giờ** thấy tài liệu hạn chế, ở cả search, semantic lẫn get-text. Đây là bất biến bắt buộc, phải có test.
- **NFR-2 Không rò rỉ bí mật**: credential/token service account không nằm trong image, không xuất hiện trong log.
- **NFR-3 Hiệu năng**: search metadata/full-text p95 < 1.5s trong LAN; semantic search p95 < 2s ở quy mô ~vài trăm nghìn chunk.
- **NFR-4 Tương thích phiên bản**: chuyển 6.3 → v10 chỉ bằng đổi config adapter, không sửa tool.
- **NFR-5 Tiếng Việt**: tìm được cả khi gõ có dấu/không dấu; ưu tiên đúng theo dấu.
- **NFR-6 Quan trắc**: log có request-id, key-id, tool, độ trễ; có health check; audit truy cập tài liệu hạn chế.
- **NFR-7 Khả mở**: thêm nguồn mới = thêm 1 class provider + config, không đụng lõi.
- **NFR-8 Chi phí**: theo dõi được số token embedding tiêu thụ (để dự toán khi index toàn kho).

## 5. Ràng buộc

- Ngôn ngữ: Python + FastMCP. Lưu trữ vector: PostgreSQL + pgvector (đồng bộ stack RAG).
- Embedding: Gemini `gemini-embedding-001`, **1536 chiều** (khớp RAG hiện tại).
- Không phá vỡ hoạt động Solr/DSpace đang chạy (chỉ đọc; embedding chạy theo batch có điều tiết).

## 6. Tiêu chí thành công Giai đoạn 1

1. RAG chatbot gọi được `semantic_search_documents` và trích dẫn đúng tài liệu thư viện.
2. Đối tác ngoài tra được tài liệu công khai, và **không** chạm được tài liệu hạn chế (có test chứng minh).
3. Chuyển sang v10 (khi tới) không phải viết lại tool.
