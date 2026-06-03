# Phase 2 — Corpus Infrastructure — Design Spec

**Date:** 2026-05-30
**Status:** Approved
**Parent spec:** [`2026-05-30-intent-router-and-knowledge-qa-design.md`](./2026-05-30-intent-router-and-knowledge-qa-design.md)

## Mục đích

Dựng nền tảng lưu trữ tài liệu unstructured (vector store) để **Phase 3** ingest dữ liệu vào và **Phase 4** (KnowledgeQA RAG) query được. Phase 2 chỉ làm hạ tầng — schema, index, repository, ops — **chưa** crawl data (Phase 3) và **chưa** trả lời câu hỏi (Phase 4).

## Bối cảnh hiện trạng (từ codebase)

Ba phát hiện định hình toàn bộ thiết kế:

1. **`raw_documents` đã tồn tại** (`db/migrations/003_raw_documents.sql`) phục vụ admission ingestion với schema fetch-pipeline (`url`, `raw_content BYTEA`, `parsed_text`, `content_hash`…). **Không tái sử dụng, không sửa** bảng này.
2. **Chưa có hạ tầng vector nào.** Postgres hiện là `postgres:16-alpine` (không có pgvector); **không có embedding call** ở đâu trong code.
3. **Provider LLM là Google Gemini** (`google-genai`) qua abstraction `services/inference/providers/`. Chưa cấu hình embedding model.

Pattern hiện có cần tuân theo:
- **Migrations:** file `.sql` trong `db/migrations/`, chạy theo thứ tự glob bởi `db/setup_db.py`, idempotent bằng `IF NOT EXISTS`. Không có bảng version tracking.
- **Repository:** psycopg2 thuần, connection-per-call, `connection_factory` injectable, Pydantic models, `Json(jsonable_encoder(...))` cho cột JSONB (xem `services/chat/repository.py`).

## Quyết định nền tảng

| Hạng mục | Quyết định | Lý do |
|---|---|---|
| Vector store | **pgvector** (cùng Postgres) | Một query lọc metadata + ANN; không vận hành store riêng |
| Postgres image | `postgres:16-alpine` → **`pgvector/pgvector:pg16`** | Drop-in, giữ nguyên volume `advisory_pgdata` |
| Embedding model | **`gemini-embedding-001`, `output_dimensionality=768`** | Đa ngôn ngữ tốt (tiếng Việt), Matryoshka → 768 giữ chất lượng, index nhỏ/nhanh |
| Distance | **cosine** (`vector_cosine_ops`), vector **L2-normalized** | Gemini khuyến nghị normalize khi dims < 3072 |
| Tên bảng | **`knowledge_documents`** + **`knowledge_chunks`** | Namespace riêng, không đụng admission |
| Dimension constant | `EMBEDDING_DIM = 768` trong `ingestion/config/settings.py` | Một nguồn sự thật; đổi dims = re-embed toàn bộ |

> **Lưu ý vận hành:** đổi `EMBEDDING_DIM` về sau yêu cầu re-embed toàn corpus (kiểu cột `vector(N)` cố định). Chốt một lần.

## 1. Schema — `db/migrations/013_knowledge_corpus.sql`

Một migration idempotent duy nhất; statement đầu bật extension:

```sql
CREATE EXTENSION IF NOT EXISTS vector;

-- Parent: một dòng cho mỗi tài liệu nguồn đã fetch
CREATE TABLE IF NOT EXISTS knowledge_documents (
    id              SERIAL PRIMARY KEY,
    school          TEXT NOT NULL,
    document_type   TEXT NOT NULL,          -- tuition_page | curriculum_pdf | faq | handbook | scholarship_policy
    source_url      TEXT NOT NULL UNIQUE,   -- UNIQUE → re-fetch upsert, không duplicate
    content_hash    TEXT,                   -- change detection khi re-fetch
    raw_text        TEXT,
    fetched_at      TIMESTAMPTZ DEFAULT NOW(),
    ingested_at     TIMESTAMPTZ DEFAULT NOW()
);

-- Child: đơn vị chunk + embedding để retrieval
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id                    SERIAL PRIMARY KEY,
    knowledge_document_id INTEGER REFERENCES knowledge_documents(id) ON DELETE CASCADE,
    school                TEXT NOT NULL,
    program               TEXT,
    year                  INTEGER,
    document_type         TEXT,
    topic                 TEXT,             -- tuition | curriculum | scholarship | dormitory | career | ...
    chunk_text            TEXT NOT NULL,
    embedding             vector(768),      -- nullable: cho phép chunk-then-embed / re-embed
    source_url            TEXT,
    span_start            INTEGER,
    span_end              INTEGER,
    ingested_at           TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (source_url, span_start, span_end)   -- idempotency key cho Phase 3 re-run
);
```

Hai lựa chọn có chủ đích:
- **`embedding` nullable** — tách chunking khỏi embedding: re-embed (đổi model) không cần re-fetch; embed lỗi không mất chunk.
- **`UNIQUE (source_url, span_start, span_end)`** — idempotency key thoả tiêu chí Phase 3 ("không duplicate cho cùng source_url + span") qua `ON CONFLICT`.

## 2. Indexes

```sql
-- Metadata filter (Phase 4 lọc school + topic trước vector search)
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_school_topic
    ON knowledge_chunks (school, topic);

-- ANN vector index — HNSW với cosine distance
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding
    ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);
```

**HNSW thay vì IVFFlat:** không cần training (IVFFlat cần data sẵn để build lists tốt; HNSW build tăng dần khi ingest), recall/latency tốt hơn ở quy mô này, hoạt động trên bảng rỗng ban đầu.

## 3. `KnowledgeChunkRepository` — package `services/knowledge/`

Package mới `services/knowledge/`, theo **đúng pattern psycopg2** của `services/chat/repository.py` (injectable `connection_factory`, connection-per-call, Pydantic models trong `services/knowledge/models.py`).

```python
# services/knowledge/models.py
class KnowledgeChunk(BaseModel):
    school: str
    topic: str | None = None
    program: str | None = None
    year: int | None = None
    document_type: str | None = None
    chunk_text: str
    embedding: list[float] | None = None
    source_url: str | None = None
    span_start: int | None = None
    span_end: int | None = None

class ScoredChunk(KnowledgeChunk):
    score: float    # cosine similarity (Phase 4 thresholds trên đây)

# services/knowledge/repository.py
class KnowledgeChunkRepository:
    def upsert_chunk(self, chunk: KnowledgeChunk) -> int:
        # INSERT ... ON CONFLICT (source_url, span_start, span_end)
        #   DO UPDATE SET chunk_text=..., embedding=..., ingested_at=NOW()
        # → trả về chunk id

    def search_by_metadata(self, school: str, topic: str | None = None,
                           limit: int = 20) -> list[KnowledgeChunk]:
        # WHERE school=%s [AND topic=%s] — dùng idx_knowledge_chunks_school_topic

    def vector_search(self, embedding: list[float], school: str | None = None,
                      topic: str | None = None, limit: int = 5) -> list[ScoredChunk]:
        # SELECT ..., 1 - (embedding <=> %s) AS score
        # [WHERE school/topic] ORDER BY embedding <=> %s LIMIT %s
```

`vector_search` gộp metadata filter + ANN scan `<=>` trong một query — đúng bước `metadata filter → vector search` của Phase 4. Embedding truyền dưới dạng pgvector literal qua adapter `pgvector.psycopg2` (thêm `pgvector` vào `requirements.txt`).

## 4. Testing Strategy

pgvector không chạy in-memory được, nên chia hai tầng:

- **Unit test logic** với **fake `connection_factory`** (stub ghi lại SQL + params), không cần DB thật — giống cách `services/chat` test được:
  - `upsert_chunk` dựng đúng câu `ON CONFLICT`
  - `search_by_metadata` bỏ mệnh đề `topic` khi `None`
  - `vector_search` format vector literal đúng và áp filter
- **Một integration test** gated sau test database có pgvector, **auto-skip** (`pytest.mark.skipif`) khi không có DB: round-trip thật `upsert_chunk` → `vector_search` trả đúng chunk theo thứ tự similarity. Đây là bằng chứng "vector index hoạt động với dim 768".

File test: `tests/services/knowledge/test_repository.py`.

## 5. Ops Changes

- `docker-compose.yml`: image `postgres:16-alpine` → `pgvector/pgvector:pg16` (giữ volume, data preserved)
- `requirements.txt`: thêm `pgvector`
- `ingestion/config/settings.py`: thêm `EMBEDDING_DIM = 768`, `GEMINI_EMBEDDING_MODEL = "gemini-embedding-001"`
- `db/setup_db.py`: thêm `knowledge_documents`, `knowledge_chunks` vào danh sách `expected` của `verify_tables()`

## Acceptance Criteria

- [ ] Migration `013` tạo 2 bảng + extension idempotent, tích hợp vào glob runner của `db/setup_db.py`
- [ ] `idx_knowledge_chunks_school_topic` và HNSW embedding index tồn tại sau migration
- [ ] HNSW index hoạt động với `vector(768)` (chứng minh bằng integration test gated)
- [ ] `KnowledgeChunkRepository` có đủ 3 operations với unit test (fake factory) + 1 round-trip test gated
- [ ] Không thay đổi `raw_documents` hay bất kỳ bảng/pipeline admission structured nào hiện tại

## Không thay đổi

- Bảng `raw_documents` và toàn bộ admission ingestion pipeline hiện tại
- Structured admission data schema
- Advisory graph và ConversationService (Phase 1)

## Dependencies

- **Phase 2 phải xong trước Phase 3** (data collection cần schema + repository để upsert)
- **Phase 3 phải xong trước Phase 4** (RAG agent cần data đã ingest)
