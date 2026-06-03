# Phase 3 — Data Collection — Design Spec

**Date:** 2026-05-30
**Status:** Approved
**Parent spec:** [`2026-05-30-intent-router-and-knowledge-qa-design.md`](./2026-05-30-intent-router-and-knowledge-qa-design.md)
**Depends on:** [`2026-05-30-phase-2-corpus-infrastructure-design.md`](./2026-05-30-phase-2-corpus-infrastructure-design.md)

## Mục đích

Crawl và ingest tài liệu unstructured (HTML/PDF) từ các nguồn trường vào corpus `knowledge_documents` + `knowledge_chunks` đã dựng ở Phase 2, để **Phase 4** (KnowledgeQA RAG) query được. Phase 3 làm **pipeline thu thập dữ liệu**: fetch → parse → chunk → embed → upsert, idempotent và tối ưu chi phí embedding.

## Bối cảnh hiện trạng (từ codebase)

Bốn phát hiện định hình thiết kế:

1. **Hạ tầng fetch/parse generic đã có và đã kiểm chứng.** `http_fetch()` (`ingestion/fetchers/http_fetcher.py`: retry, SSL toggle, content_hash, user-agent rotation), `parse_html()` (`ingestion/parsers/html_parser.py`: BeautifulSoup, lấy main content + text sạch), `parse_pdf()` (`ingestion/parsers/pdf_parser.py`: pdfminer + tabula). Đây là raw text mà corpus cần.
2. **Chưa có code embedding ở đâu.** `GeminiProvider` (`services/inference/providers/gemini_provider.py`) chỉ có `generate_content`. Phase 2 đã thêm hằng `GEMINI_EMBEDDING_MODEL = "gemini-embedding-001"` + `EMBEDDING_DIM = 768` vào `ingestion/config/settings.py` nhưng chưa có lời gọi nào.
3. **`knowledge_documents` chưa có repository.** Phase 2 chỉ làm `KnowledgeChunkRepository` (`upsert_chunk`, `search_by_metadata`, `vector_search`). Cần thêm repo cho bảng parent.
4. **Schema Phase 2 đầy đủ cho Phase 3.** `knowledge_chunks` có sẵn idempotency key `UNIQUE (source_url, span_start, span_end)`, FK `knowledge_document_id`, cột `embedding vector(768)` nullable. Phase 3 **không cần migration mới**.

Pattern phải tuân theo:
- **Repository:** psycopg2 thuần, connection-per-call, `connection_factory` injectable, Pydantic models, vector truyền dạng literal `[..]::vector` (xem `services/knowledge/repository.py`).
- **Pipeline:** orchestrator class với `run_for_source` / `run_for_school` / `run_all`, lỗi 1 nguồn không chặn nguồn khác (xem `ingestion/pipeline/ingestion_pipeline.py`).
- **Registry:** seed JSON + pydantic model + loader (xem `ingestion/registry/`).

## Quyết định nền tảng

| Hạng mục | Quyết định | Lý do |
|---|---|---|
| Tái sử dụng fetch/parse | **Reuse tối đa** `http_fetch`, `parse_html`, `parse_pdf` | Primitive đã kiểm chứng; chỉ *gọi*, không sửa → admission pipeline không bị chạm |
| PDF page-aware | Lớp mỏng MỚI `pdf_pages.py` (pdfplumber) | `parse_pdf` gộp text, mất ranh giới trang; acceptance criteria yêu cầu giữ page |
| Chunking | **Structure-aware char window**, ~1800 ký tự, overlap ~256 | Không cần tokenizer; span = offset ký tự → deterministic → idempotent; tránh cắt giữa câu |
| Page metadata | **Marker `[Trang N]` trong `chunk_text`** | Không đổi schema; page hiện trong citation Phase 4 |
| Embedding execution | **Inline + batch** (mỗi document một lượt) | Đơn giản end-to-end; embedder cô lập để backfill sau |
| Freshness | **Hash hai tầng** (content_hash gate + per-chunk reuse map) | Re-run rẻ + idempotent; chỉ embed đoạn text MỚI; không orphan |
| Schema | **Không migration mới** | Reuse map dựng trong bộ nhớ từ chunk cũ của chính document |

## 1. Cây thư mục

```
ingestion/knowledge/                  ← TẤT CẢ là code MỚI
  __init__.py
  registry/
    __init__.py
    models.py              KnowledgeSource (pydantic)
    knowledge_registry.py  loader đọc seed JSON
    seeds/knowledge_sources.json
  pdf_pages.py             lớp PDF page-aware MỎNG (pdfplumber)
  chunker.py              structure-aware char window
  embedder.py             Gemini embed + L2-normalize + batch
  pipeline.py             orchestrate + CLI entry
  verify_corpus.py        script kiểm tra sau ingest
  _fixtures/              HTML/PDF nhỏ cho test

services/knowledge/
  models.py               ← MỞ RỘNG (thêm KnowledgeDocument)
  repository.py           ← MỞ RỘNG (KnowledgeDocumentRepository + helper trên chunk repo)

REUSE nguyên trạng (KHÔNG sửa):
  ingestion/fetchers/http_fetcher.py    → http_fetch()
  ingestion/parsers/html_parser.py      → parse_html()
  ingestion/parsers/pdf_parser.py       → parse_pdf()  (PDF không cần tách trang)
```

## 2. Registry knowledge

`SourceEntry` của admission không có `topic`/`document_type`, nên model riêng.

```python
# ingestion/knowledge/registry/models.py
class KnowledgeSource(BaseModel):
    school: str                 # "VNU-UET" | "HUST" | "NEU"
    source_url: str
    document_type: str          # taxonomy bên dưới — validate khi load
    topic: str                  # 1 trong 7 KnowledgeTopic — validate khi load
    fetch_strategy: str = "http"
    program: str | None = None  # ngành cụ thể nếu có
    year: int | None = None
    active: bool = True
```

**Taxonomy chốt cứng** (loader raise nếu sai):

- `topic` ∈ `tuition, curriculum, scholarship, dormitory, career, admission_policy, program_overview` (7 giá trị `KnowledgeTopic` ở parent spec)
- `document_type` ∈ `tuition_page, curriculum_pdf, scholarship_policy, faq, handbook, program_overview_page, career_page, dormitory_page`

`knowledge_registry.py`: loader đọc `seeds/knowledge_sources.json`, validate từng entry qua `KnowledgeSource`, expose `all_sources()`, `get_sources_by_school(school)`.

Seed `knowledge_sources.json`: ≥ 3 trường (HUST, NEU, VNU-UET), mỗi trường ≥ 2 `document_type`.

## 3. Fetch & Parse

- **Fetch:** gọi thẳng `http_fetch(url)` → `FetchResult` có `raw_content` (bytes) + `content_hash` (sha256). Không viết lại.
- **Phân loại HTML vs PDF:** dựa `content_type` của `FetchResult` (và/hoặc đuôi URL).
- **Parse HTML:** `parse_html(content).text` → text sạch.
- **Parse PDF page-aware:** `ingestion/knowledge/pdf_pages.py` mới:
  ```python
  def extract_pages(content: bytes) -> list[tuple[int, str]]:
      # pdfplumber.open → duyệt pdf.pages → [(page_no, page_text), ...]
  ```
  Pipeline ghép thành 1 chuỗi text, chèn marker `[Trang N]\n` đầu mỗi trang. Đây là nguồn để chunker mang marker vào `chunk_text`.

## 4. Chunker — structure-aware char window

```python
# ingestion/knowledge/chunker.py
@dataclass
class Chunk:
    chunk_text: str
    span_start: int   # offset ký tự trong text đầy đủ
    span_end: int

def chunk_text(text: str, size: int = CHUNK_SIZE,
               overlap: int = CHUNK_OVERLAP) -> list[Chunk]: ...
```

Thuật toán:

1. Tách `text` thành **block** theo ranh giới tự nhiên: dòng trống (`\n\n`), heading, ranh giới `[Trang N]`.
2. **Đóng gói** các block liên tiếp vào cửa sổ tối đa `CHUNK_SIZE` ký tự. Không cắt giữa block, trừ khi một block đơn vượt cửa sổ → hard-split tại ranh giới câu gần nhất (`. `, `\n`).
3. **Overlap** `CHUNK_OVERLAP` ký tự: chunk kế tiếp bắt đầu lùi lại `overlap` ký tự để giữ ngữ cảnh.
4. **Span** `(span_start, span_end)` = offset ký tự trong `text` đầy đủ → **deterministic** ⇒ idempotency key `(source_url, span_start, span_end)` ổn định khi nội dung không đổi.
5. Marker `[Trang N]` nằm trong text nên tự động vào `chunk_text` của chunk chứa nó → page hiện trong citation Phase 4.

Hằng số mới trong `ingestion/config/settings.py`:
```python
CHUNK_SIZE = int(os.getenv("KNOWLEDGE_CHUNK_SIZE", 1800))     # ≈ 512 token tiếng Việt
CHUNK_OVERLAP = int(os.getenv("KNOWLEDGE_CHUNK_OVERLAP", 256))
```

## 5. Embedder

`ingestion/knowledge/embedder.py` — cô lập 100% lời gọi Gemini để mock được:

```python
class GeminiEmbedder:
    def __init__(self, api_key: str | None = None,
                 model: str = GEMINI_EMBEDDING_MODEL,
                 dim: int = EMBEDDING_DIM): ...

    def embed(self, texts: list[str]) -> list[list[float]]:
        # client.models.embed_content(
        #     model=self.model, contents=batch,
        #     config=EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT",
        #                               output_dimensionality=self.dim))
        # → L2-normalize từng vector (Gemini khuyến nghị khi dim < 3072)
        # → batch ≤ 100 texts/call
```

- `task_type="RETRIEVAL_DOCUMENT"` cho corpus (Phase 4 query dùng `RETRIEVAL_QUERY`).
- **Batch** ≤ 100 chunk/call giảm round-trip & rate-limit.
- Interface injectable: pipeline nhận `embedder` qua constructor; test dùng `FakeEmbedder` trả vector deterministic theo nội dung.

## 6. Hash hai tầng — freshness + tối ưu embedding

**Không đổi schema.** Hai tầng kiểm tra trùng lặp:

**Tầng document — `content_hash` gate:**
```
fetch → content_hash = sha256(raw_content)
existing = doc_repo.get_document_by_url(url)
if existing and existing.content_hash == content_hash:
    skip toàn bộ (không parse/chunk/embed)   # re-run rẻ & idempotent
    return
```

**Tầng chunk — reuse map (chỉ chạy khi document ĐỔI hoặc MỚI):**
```
1. doc_id = doc_repo.get_or_create_document(...)          # insert nếu mới; KHÔNG ghi content_hash mới ở đây
2. prev = chunk_repo.get_embedding_map_for_document(doc_id)
        → { sha256(chunk_text): embedding }               # đọc TRƯỚC khi xóa; chunk cũ vẫn còn
3. new_chunks = chunk_text(full_text)
4. to_embed = []
   for c in new_chunks:
       c.embedding = prev.get(sha256(c.chunk_text))        # TÁI SỬ DỤNG, không gọi API
       if c.embedding is None: to_embed.append(c)
5. vectors = embedder.embed([c.chunk_text for c in to_embed])   # chỉ embed đoạn text MỚI
   gán vectors vào to_embed
6. chunk_repo.delete_chunks_for_document(doc_id)           # xóa sạch chunk cũ → không orphan
7. for c in new_chunks: chunk_repo.upsert_chunk(...)       # embedding tái dùng hoặc mới
8. doc_repo.mark_ingested(doc_id, content_hash)           # FINAL — ghi content_hash SAU khi chunks đã commit
```

Kết quả: trang cập nhật một con số học phí → chỉ vài chunk đổi được embed lại; các đoạn giống hệt **dùng lại embedding cũ**. Không cần cột `chunk_hash` vì map dựng trong bộ nhớ từ chunk cũ của chính document.

> **Lưu ý thứ tự (an toàn khi crash):**
> - Đọc reuse map (bước 2) phải **trước** khi xóa chunk cũ (bước 6). Cùng `doc_id`, chunk cũ vẫn tồn tại sau `get_or_create_document` (chỉ chạm hàng parent, không đụng chunks).
> - Ghi `content_hash` (bước 8) là bước **cuối cùng**, sau khi chunks đã commit. Nếu pipeline crash giữa chừng, `content_hash` vẫn là giá trị cũ → lần chạy sau **reprocess lại** thay vì skip nhầm document còn dở.

## 7. Repository — mở rộng `services/knowledge/`

```python
# services/knowledge/models.py — thêm
class KnowledgeDocument(BaseModel):
    school: str
    document_type: str
    source_url: str
    content_hash: str | None = None
    raw_text: str | None = None
    id: int | None = None

# services/knowledge/repository.py — thêm class mới
class KnowledgeDocumentRepository:
    def __init__(self, connection_factory=get_knowledge_db_connection): ...
    def get_document_by_url(self, url: str) -> KnowledgeDocument | None:
        # dùng cho content_hash gate (§6 tầng document)
    def get_or_create_document(self, doc: KnowledgeDocument) -> int:
        # INSERT ... ON CONFLICT (source_url) DO UPDATE
        #   SET school=..., document_type=..., raw_text=..., fetched_at=NOW()
        # → trả id. KHÔNG ghi content_hash ở đây (xem mark_ingested).
    def mark_ingested(self, doc_id: int, content_hash: str) -> None:
        # UPDATE knowledge_documents SET content_hash=%s, ingested_at=NOW()
        #   WHERE id=%s — bước cuối, sau khi chunks đã commit (§6 bước 8)

# services/knowledge/repository.py — thêm vào KnowledgeChunkRepository
    def get_embedding_map_for_document(self, doc_id: int) -> dict[str, list[float]]:
        # SELECT chunk_text, embedding FROM knowledge_chunks
        #   WHERE knowledge_document_id=%s AND embedding IS NOT NULL
        # → { sha256(chunk_text): parse_vector(embedding) }
    def delete_chunks_for_document(self, doc_id: int) -> int:
        # DELETE FROM knowledge_chunks WHERE knowledge_document_id=%s
```

Cùng pattern psycopg2 / `connection_factory` injectable. Vector đọc về dạng text `[..]` → parse thành `list[float]`.

## 8. Pipeline orchestration + CLI

```python
# ingestion/knowledge/pipeline.py
class KnowledgePipeline:
    def __init__(self, registry=None, embedder=None,
                 doc_repo=None, chunk_repo=None): ...        # tất cả injectable để test
    def run_for_source(self, source: KnowledgeSource) -> KnowledgeIngestResult:
        # đủ 6 bước §6; trả { skipped, chunks_total, chunks_embedded, chunks_reused }
    def run_for_school(self, school: str):
        # try/except mỗi source — lỗi 1 nguồn không chặn nguồn khác
    def run_all(self): ...
```

CLI: `python -m ingestion.knowledge.pipeline [--school HUST | --all]`. Mỗi source log: số chunk embed mới / tái dùng / skip.

## 9. Verify script

`python -m ingestion.knowledge.verify_corpus`:
- Đếm chunk theo `(school, topic)`, in bảng.
- **Flag** trường/topic có 0 chunk (thiếu data).
- Cảnh báo chunk `embedding IS NULL` (embed sót).
- Exit code ≠ 0 nếu có trường trong registry hoàn toàn thiếu data (dùng được trong CI sau này).

## 10. Testing Strategy

**Unit (fake, không cần DB):**
- `chunker`: span deterministic & liền mạch, overlap đúng, không cắt giữa block, hard-split block dài, marker `[Trang N]` được giữ trong chunk.
- `embedder`: mock client → assert L2-normalize (‖v‖≈1), batch ≤ 100, `task_type` đúng.
- `knowledge_registry`: load seed hợp lệ; reject `topic`/`document_type` ngoài taxonomy.
- `KnowledgeDocumentRepository` + chunk helper: fake `connection_factory` bắt SQL + params (`upsert_document` dựng đúng `ON CONFLICT (source_url)`; `delete_chunks_for_document` đúng WHERE).
- `KnowledgePipeline` với fake fetch/embed/repo:
  - document unchanged (cùng content_hash) → **skip**, embedder không được gọi.
  - document changed → reuse map đúng: chunk text trùng dùng lại vector, chunk mới mới gọi embed.
  - chunk cũ (orphan) bị `delete_chunks_for_document` trước khi insert.

**Gated integration (auto-skip `pytest.mark.skipif` khi không có DB pgvector):**
- Ingest 1 fixture (HTML + PDF) → verify đếm đúng số chunk per (school, topic).
- Re-run lần 2 → **0 embed mới** (idempotent), số chunk không đổi.

Fixtures HTML/PDF nhỏ trong `ingestion/knowledge/_fixtures/`.

## Acceptance Criteria

- [ ] ≥ 3 trường (HUST, NEU, VNU-UET) có registry entry với ≥ 2 `document_type` mỗi trường
- [ ] Pipeline chạy end-to-end: fetch → parse → chunk → embed → upsert
- [ ] Re-run là idempotent (không tạo duplicate cho cùng `source_url + span`); document không đổi → skip, 0 embed mới
- [ ] Embed tối ưu: document đổi nhưng chunk text trùng → tái dùng embedding cũ, chỉ embed đoạn mới
- [ ] PDF parser xử lý file nhiều trang, giữ metadata trang qua marker `[Trang N]` trong `chunk_text`
- [ ] Script verify sau ingest: đếm chunks per school/topic, flag trường thiếu data
- [ ] Không ảnh hưởng đến admission ingestion pipeline hiện tại (chỉ *gọi* primitive; registry/bảng/repo riêng)
- [ ] Unit test phủ chunker, embedder, registry, repository, pipeline; 1 integration test gated round-trip

## Không thay đổi

- Admission ingestion pipeline, `raw_documents`, structured admission schema
- Advisory graph và ConversationService (Phase 1)
- Schema Phase 2 (`knowledge_documents` / `knowledge_chunks`) — **không migration mới**
- `http_fetch`, `parse_html`, `parse_pdf` — chỉ gọi, không sửa

## Dependencies

- **Phase 2 phải xong trước Phase 3** (cần schema + chunk repository) ✅ đã xong
- **Phase 3 phải xong trước Phase 4** (RAG agent cần data đã ingest)
