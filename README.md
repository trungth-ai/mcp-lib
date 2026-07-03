# HPU Library MCP Server — Bộ tài liệu kế hoạch

> Trạng thái: **ĐANG CODE — Sprint 5 xong (2026-07-03), GĐ1 đã code hết cả 6 sprint.**
> Còn thiếu Sprint 0 thật (verify hạ tầng LAN) và build/run Docker thật (máy dev không có
> Docker). Xem tiến độ sống ở
> [docs/PLAN.md](docs/PLAN.md), quyết định implementation ở [docs/DECISIONS.md](docs/DECISIONS.md).
> Bộ tài liệu này do lệnh `/plan-hpu-library-mcp` sinh ra, viết đầy đủ theo yêu
> cầu (không dừng ở outline).

## Mục tiêu một câu

Biến hệ thống tri thức số của HPU (khởi đầu là thư viện DSpace `lib.hpu.edu.vn`)
thành một **MCP Server** mà mọi tác tử AI của trường — RAG chatbot, agent tư vấn
tuyển sinh, Claude Code, đối tác ngoài — gọi được qua một cổng duy nhất, an toàn,
có phân quyền, và **tìm kiếm được cả trong nội dung tài liệu** chứ không chỉ metadata.

## Chỉ mục tài liệu

| File | Nội dung |
|---|---|
| [01-requirements.md](01-requirements.md) | Yêu cầu chức năng & phi chức năng, phạm vi GĐ1 vs roadmap |
| [02-architecture.md](02-architecture.md) | Kiến trúc, deployment topology, ResourceProvider, adapter phiên bản, pipeline ngữ nghĩa |
| [03-tools-spec.md](03-tools-spec.md) | Đặc tả từng MCP tool + JSON schema I/O + ví dụ |
| [04-data-model.md](04-data-model.md) | Schema tài nguyên chuẩn hóa, mức truy cập, schema pgvector |
| [05-security.md](05-security.md) | Xác thực, phân tầng quyền theo API key, secret, audit |
| [06-test-plan.md](06-test-plan.md) | Chiến lược test, unit/integration, test tiếng Việt & test phân quyền |
| [07-sprints.md](07-sprints.md) | Sprint breakdown: đầu việc, tiêu chí nghiệm thu, ước lượng, phụ thuộc |

## Quyết định đã chốt (anh Trung)

1. **Service account riêng, quyền đọc** cho MCP đăng nhập DSpace (không dùng tài khoản cá nhân).
2. **Phân tầng quyền theo API key**: key đối tác ngoài chỉ thấy tài liệu công khai; key nội bộ thấy rộng hơn.
3. **Embedding**: dùng **Gemini embedding (1536 chiều, `gemini-embedding-001`)** để đồng bộ với RAG hiện có; tầng vector thiết kế **tháo lắp được** để nâng cấp RAG sau (đổi embedding / thêm reranker / hybrid search).

## Bối cảnh hạ tầng (đã chốt)

- **Host DSpace/Solr**: LAN `10.1.0.205` · public `27.72.202.11` · Windows · Traefik.
  *Việc chặn Solr public & cấu hình Traefik do anh Trung tự xử lý — ngoài phạm vi dự án này.*
- **Host MCP**: LAN `10.1.0.207` · public `27.72.202.13` · **Ubuntu + Docker**. Domain `mcp-lib.hpu.edu.vn`.
- **DSpace 6.3 hiện tại** (REST cũ `/rest`), **dự kiến lên v10 trong ~2 tháng** (REST mới `/server/api`) → thiết kế adapter theo phiên bản.

## Giả định cần kiểm chứng ở Sprint 0 (chưa được coi là chắc)

- Endpoint `/rest` của DSpace 6.3 còn bật.
- Tên các Solr core thực tế (`search`, `statistics`, `oai`, `authority`).
- **Field full-text trong Solr đã được index chưa** (đã chạy `filter-media` + `index-discovery`) và tên field (giả định `fulltext`).
- Bộ phân tích (analyzer) tiếng Việt trong Solr đang cấu hình thế nào.
- Phạm vi quyền của service account (đọc được tài liệu hạn chế tới đâu).

Chi tiết cách kiểm chứng: xem [07-sprints.md](07-sprints.md) → **Sprint 0**.
