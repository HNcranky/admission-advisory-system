# Plan 04: vector_search NULL-Topic Wildcard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chunk có `topic IS NULL` (PDF local đa chủ đề) luôn là ứng viên trong `vector_search` khi caller lọc theo topic; chunk web source (topic cụ thể) giữ nguyên hành vi lọc cứng.

**Architecture:** Đổi đúng 1 điều kiện SQL trong `KnowledgeChunkRepository.vector_search` (`services/knowledge/repository.py:198-200`): `AND topic = %s` → `AND (topic = %s OR topic IS NULL)`. `search_by_metadata` **giữ nguyên** (caller truyền topic tường minh). Vector similarity quyết định thứ hạng giữa chunk NULL-topic và chunk đúng topic.

**Tech Stack:** psycopg2 + pgvector; unit test bằng `FakeConnection` capture SQL, integration test cần Docker DB (pattern `pytest.mark.integration` sẵn có).

**Phụ thuộc:** Không — độc lập hoàn toàn với các plan khác, có thể làm bất kỳ lúc nào.

---

## Bối cảnh cho người chưa biết codebase

- `vector_search` build SQL động: filter `school`/`topic` chỉ thêm khi khác `None`
  (`services/knowledge/repository.py:187-207`). Cơ chế topic-hard-filter sinh ra cho
  web source 1-trang-1-chủ-đề; PDF chính thức đa chủ đề sẽ ingest với `topic=NULL`
  (Plan 05) — nếu không sửa, mọi câu hỏi có topic sẽ không bao giờ thấy chunk PDF.
- Unit test repo dùng `FakeConnection`/`FakeCursor` capture `(sql, params)` —
  xem `tests/services/knowledge/test_repository.py:5-40`.
- Integration test cần DB: `docker compose up -d --wait db` rồi
  `.\.venv\Scripts\python.exe -m db.setup_db`; fixture tự skip nếu DB không chạy
  (`tests/services/knowledge/test_repository_integration.py:16-31`).
- **Chú ý:** test hiện có `test_vector_search_builds_cosine_query_with_filters`
  (`tests/services/knowledge/test_repository.py:165`) assert chuỗi `"AND topic = %s"` —
  phải cập nhật cùng lúc, nếu không sẽ đỏ sau khi sửa SQL.

---

### Task 1: Unit test + sửa SQL

**Files:**
- Modify: `services/knowledge/repository.py:198-200`
- Modify: `tests/services/knowledge/test_repository.py:152-169` (assertion cũ) + thêm test mới cuối file

- [ ] **Step 1: Viết failing test**

Thêm vào cuối `tests/services/knowledge/test_repository.py`:

```python
def test_vector_search_topic_filter_includes_null_topic_chunks():
    # PDF local ingest với topic=NULL — NULL là wildcard, không bị lọc rớt.
    connection = FakeConnection(fetchall_return=[])
    repo = _repo(connection)

    repo.vector_search([0.1, 0.2], school="VNU-UET", topic="tuition", limit=3)

    sql, params = connection.cursor_obj.statements[0]
    assert "AND (topic = %s OR topic IS NULL)" in sql
    assert params == ("[0.1,0.2]", "VNU-UET", "tuition", "[0.1,0.2]", 3)


def test_search_by_metadata_topic_filter_stays_strict():
    # Regression: search_by_metadata caller truyền topic tường minh → vẫn lọc cứng.
    connection = FakeConnection(fetchall_return=[])
    repo = _repo(connection)

    repo.search_by_metadata("VNU-UET", topic="tuition")

    sql, _ = connection.cursor_obj.statements[0]
    assert "AND topic = %s" in sql
    assert "IS NULL" not in sql
```

Đồng thời sửa assertion trong test hiện có `test_vector_search_builds_cosine_query_with_filters` (dòng `assert "AND topic = %s" in sql`):

```python
    assert "AND (topic = %s OR topic IS NULL)" in sql
```

(`params` của test đó giữ nguyên — số placeholder không đổi.)

- [ ] **Step 2: Chạy test, xác nhận fail đúng chỗ**

Run: `.\.venv\Scripts\python.exe -m pytest tests\services\knowledge\test_repository.py -q`
Expected: `test_vector_search_topic_filter_includes_null_topic_chunks` và
`test_vector_search_builds_cosine_query_with_filters` FAILED (SQL chưa có `IS NULL`);
`test_search_by_metadata_topic_filter_stays_strict` PASS.

- [ ] **Step 3: Sửa SQL trong `vector_search`**

Trong `services/knowledge/repository.py`, method `vector_search`, thay:

```python
        if topic is not None:
            sql += " AND topic = %s"
            params.append(topic)
```

bằng:

```python
        if topic is not None:
            # NULL topic = wildcard: locally-ingested official PDFs are
            # multi-topic, so they stay candidates for every topic filter.
            sql += " AND (topic = %s OR topic IS NULL)"
            params.append(topic)
```

(KHÔNG đụng vào nhánh topic của `search_by_metadata` phía trên.)

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests\services\knowledge\test_repository.py -q`
Expected: tất cả PASS.

- [ ] **Step 5: Commit**

```powershell
git add services\knowledge\repository.py tests\services\knowledge\test_repository.py
git commit -m "fix: treat NULL topic as wildcard in vector_search"
```

---

### Task 2: Integration test với pgvector thật

**Files:**
- Modify: `tests/services/knowledge/test_repository_integration.py` (thêm test cuối file)

- [ ] **Step 1: Bật DB (nếu chưa chạy)**

```powershell
docker compose up -d --wait db
.\.venv\Scripts\python.exe -m db.setup_db
```

Expected: container healthy, migrations chạy idempotent.

- [ ] **Step 2: Viết test**

Thêm vào cuối `tests/services/knowledge/test_repository_integration.py`:

```python
def test_vector_search_includes_null_topic_excludes_other_topics(knowledge_repo):
    web_tuition = KnowledgeChunk(
        school="HUST", topic="tuition", chunk_text="học phí web",
        embedding=_vec(1.0, 0.0), source_url="http://x/tuition",
        span_start=0, span_end=1,
    )
    local_pdf = KnowledgeChunk(
        school="HUST", topic=None, chunk_text="quy chế pdf",
        embedding=_vec(0.9, 0.1), source_url="file:///d/quy-che-2026.pdf",
        span_start=0, span_end=1,
    )
    web_dorm = KnowledgeChunk(
        school="HUST", topic="dormitory", chunk_text="ký túc xá web",
        embedding=_vec(0.8, 0.2), source_url="http://x/dorm",
        span_start=0, span_end=1,
    )
    for chunk in (web_tuition, local_pdf, web_dorm):
        knowledge_repo.upsert_chunk(chunk)

    results = knowledge_repo.vector_search(
        _vec(1.0, 0.0), school="HUST", topic="tuition", limit=10
    )

    urls = {r.source_url for r in results}
    assert "http://x/tuition" in urls                  # đúng topic: giữ
    assert "file:///d/quy-che-2026.pdf" in urls        # NULL topic: wildcard
    assert "http://x/dorm" not in urls                 # topic khác: vẫn bị loại
```

- [ ] **Step 3: Chạy integration test, xác nhận pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests\services\knowledge\test_repository_integration.py -q`
Expected: tất cả PASS (test mới + 2 test round-trip cũ). Nếu DB không chạy, fixture sẽ skip — phải chạy với DB bật để chốt plan này.

- [ ] **Step 4: Commit**

```powershell
git add tests\services\knowledge\test_repository_integration.py
git commit -m "test: integration coverage for NULL-topic wildcard in vector_search"
```

---

## Định nghĩa hoàn thành (Plan 04)

- `vector_search(..., topic="tuition")` trả cả chunk `topic IS NULL`; chunk topic khác vẫn bị loại.
- `search_by_metadata` không đổi hành vi.
- Unit + integration đều xanh:
  `.\.venv\Scripts\python.exe -m pytest tests\services\knowledge -q` (DB bật).
