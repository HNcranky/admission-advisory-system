# National Regulations — Plan 3/3: National-scope retrieval in `qa_service`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Bộ GD&ĐT regulations (scope `school="MOET"`) bolster knowledge answers for **every school-scoped query** — woven into the single generated answer with its own retrieval budget, so national rules never crowd out a school's own chunks.

**Architecture:** Every retrieval path — the pure `KNOWLEDGE_QA` route (`conversation_service._handle_knowledge_qa`), the fan-out (`knowledge_fanout.run_knowledge_fanout`), and `compare_orchestrator` — funnels through `KnowledgeQAService.answer(school, topic)`. So the national pass lives **there, in one place**: after retrieving the school's chunks, if `school` is a specific school (not `None`, not `MOET`), run a second `vector_search(school="MOET")` with its own `national_top_k` budget, filter by `min_score`, merge, and sort by score. One change covers all call sites; separate budgets mean no dilution.

**Tech Stack:** Python 3.12, pytest, dependency injection (fake chunk repo).

**Depends on Plan 1** (`services.knowledge.scope.NATIONAL_SCHOOL`). Implements spec §3 (D1/D3) and §5.4. This replaces the original "fan-out block" idea, which missed the pure `KNOWLEDGE_QA` route.

---

### Task 1: National augmentation in `KnowledgeQAService.answer`

**Files:**
- Modify: `ingestion/config/settings.py:76-77`
- Modify: `services/knowledge/qa_service.py`
- Test: `tests/services/knowledge/test_qa_service.py` (append)

- [ ] **Step 1: Write the failing tests (append)**

```python
# append to tests/services/knowledge/test_qa_service.py
from ingestion.config.settings import KNOWLEDGE_QA_NATIONAL_TOP_K
from services.knowledge.scope import NATIONAL_SCHOOL


class RepoBySchool:
    """vector_search returns a different chunk list per school, and records calls."""

    def __init__(self, by_school):
        self._by_school = by_school
        self.calls = []

    def vector_search(self, embedding, school=None, topic=None, limit=5):
        self.calls.append({"school": school, "topic": topic, "limit": limit})
        return list(self._by_school.get(school, []))


def _service_with(repo, parsed_data, min_score=0.5, top_k=5):
    return KnowledgeQAService(
        chunk_repository=repo,
        embedder=FakeEmbedder(),
        gateway=FakeGateway(parsed_data=parsed_data),
        min_score=min_score,
        top_k=top_k,
    )


def test_specific_school_query_also_pulls_national_chunks():
    repo = RepoBySchool({
        "HUST": [_chunk("Phương thức xét tuyển HUST", "http://hust/a", 0.92,
                        school="HUST", topic="admission_policy")],
        NATIONAL_SCHOOL: [_chunk("Điểm ưu tiên khu vực tối đa 0,75",
                                 "https://chinhphu/r.pdf", 0.80,
                                 school=NATIONAL_SCHOOL, topic="admission_policy")],
    })
    service = _service_with(repo, parsed_data={"answer": "...", "used_source_ids": []})
    res = service.answer("HUST xét tuyển thế nào", school="HUST", topic="admission_policy")
    # two retrievals: the school scope, then the national scope with its own budget
    assert [c["school"] for c in repo.calls] == ["HUST", NATIONAL_SCHOOL]
    assert repo.calls[1]["limit"] == KNOWLEDGE_QA_NATIONAL_TOP_K
    # the national source is woven into the answer's citations
    assert "https://chinhphu/r.pdf" in {c.source_url for c in res.citations}


def test_no_school_query_does_not_add_national_pass():
    repo = RepoBySchool({None: [_chunk("x", "http://x", 0.9, school=None)]})
    service = _service_with(repo, parsed_data={"answer": "ok"})
    service.answer("quy chế tuyển sinh 2026", school=None, topic="admission_policy")
    assert [c["school"] for c in repo.calls] == [None]   # school=None already scans national


def test_national_school_query_does_not_recurse():
    repo = RepoBySchool({NATIONAL_SCHOOL: [
        _chunk("y", "https://chinhphu/y.pdf", 0.9, school=NATIONAL_SCHOOL)]})
    service = _service_with(repo, parsed_data={"answer": "ok"})
    service.answer("q", school=NATIONAL_SCHOOL, topic="admission_policy")
    assert [c["school"] for c in repo.calls] == [NATIONAL_SCHOOL]   # single call only


def test_low_score_national_chunks_are_dropped():
    repo = RepoBySchool({
        "HUST": [_chunk("HUST a", "http://hust/a", 0.92, school="HUST")],
        NATIONAL_SCHOOL: [_chunk("weak", "https://chinhphu/weak.pdf", 0.30,
                                 school=NATIONAL_SCHOOL)],
    })
    service = _service_with(repo,
                            parsed_data={"answer": "ans", "used_source_ids": []},
                            min_score=0.5)
    res = service.answer("q", school="HUST", topic="admission_policy")
    urls = {c.source_url for c in res.citations}
    assert "https://chinhphu/weak.pdf" not in urls   # below min_score → dropped
    assert "http://hust/a" in urls
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/services/knowledge/test_qa_service.py -q`
Expected: FAIL — `ImportError: cannot import name 'KNOWLEDGE_QA_NATIONAL_TOP_K'` (collection error), and the new behavior tests would fail.

- [ ] **Step 3: Add the settings constant**

In `ingestion/config/settings.py`, the current lines (76-77) are:

```python
KNOWLEDGE_QA_TOP_K = int(os.getenv("KNOWLEDGE_QA_TOP_K", 5))
KNOWLEDGE_QA_MIN_SCORE = float(os.getenv("KNOWLEDGE_QA_MIN_SCORE", 0.5))
```

Insert a third line just below them:

```python
KNOWLEDGE_QA_TOP_K = int(os.getenv("KNOWLEDGE_QA_TOP_K", 5))
KNOWLEDGE_QA_MIN_SCORE = float(os.getenv("KNOWLEDGE_QA_MIN_SCORE", 0.5))
# Separate, smaller budget for the national-scope (Bộ GD&ĐT) pass appended to
# every school-scoped knowledge query, so national regs never crowd out the
# school's own chunks.
KNOWLEDGE_QA_NATIONAL_TOP_K = int(os.getenv("KNOWLEDGE_QA_NATIONAL_TOP_K", 3))
```

- [ ] **Step 4: Add the national augmentation to `qa_service.py`**

In `services/knowledge/qa_service.py`, change the settings import (line 4) from:

```python
from ingestion.config.settings import KNOWLEDGE_QA_MIN_SCORE, KNOWLEDGE_QA_TOP_K
```

to:

```python
from ingestion.config.settings import (
    KNOWLEDGE_QA_MIN_SCORE, KNOWLEDGE_QA_NATIONAL_TOP_K, KNOWLEDGE_QA_TOP_K,
)
```

Add a scope import next to the other `services.knowledge` import (after line 9 `from services.knowledge.repository import KnowledgeChunkRepository`):

```python
from services.knowledge.scope import NATIONAL_SCHOOL
```

Add the `national_top_k` parameter to `__init__` (extend the signature and store it):

```python
    def __init__(
        self,
        chunk_repository=None,
        embedder=None,
        gateway=None,
        top_k: int = KNOWLEDGE_QA_TOP_K,
        min_score: float = KNOWLEDGE_QA_MIN_SCORE,
        national_top_k: int = KNOWLEDGE_QA_NATIONAL_TOP_K,
    ):
        self._chunk_repository = chunk_repository or KnowledgeChunkRepository()
        self._embedder = embedder or GeminiEmbedder()
        self._gateway = gateway or build_default_gateway()
        self._top_k = top_k
        self._min_score = min_score
        self._national_top_k = national_top_k
```

In `answer`, insert the augmentation call between the school `vector_search` and the confidence gate:

```python
    def answer(
        self,
        question: str,
        school: Optional[str],
        topic: Optional[str],
        conversation_context: str = "",
    ) -> KnowledgeQAResult:
        embedding = self._embedder.embed([question], task_type="RETRIEVAL_QUERY")[0]
        chunks = self._chunk_repository.vector_search(
            embedding, school=school, topic=topic, limit=self._top_k
        )
        chunks = self._augment_with_national(embedding, school, topic, chunks)
        confidence = chunks[0].score if chunks else 0.0
        if not chunks or confidence < self._min_score:
            return KnowledgeQAResult(has_data=False, confidence=confidence)
        return self._generate(question, chunks, confidence, conversation_context)

    def _augment_with_national(self, embedding, school, topic, chunks):
        """A school-scoped query also pulls national-scope (Bộ GD&ĐT) chunks with
        their own budget — national regulations apply to every school. The two
        scopes keep separate top_k, so national never crowds out the school's own
        chunks. Skipped when the query isn't school-scoped (school=None already
        scans national chunks) or is already national."""
        if school in (None, NATIONAL_SCHOOL):
            return chunks
        national = self._chunk_repository.vector_search(
            embedding, school=NATIONAL_SCHOOL, topic=topic,
            limit=self._national_top_k,
        )
        national = [c for c in national if c.score >= self._min_score]
        merged = list(chunks) + national
        merged.sort(key=lambda c: c.score, reverse=True)
        return merged
```

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/services/knowledge/test_qa_service.py -q`
Expected: PASS (all green — the new national tests plus every pre-existing qa_service test)

- [ ] **Step 6: Run the full knowledge + chat suites (no regressions)**

Run: `.venv/bin/python -m pytest tests/services/knowledge tests/services/chat -q`
Expected: PASS (existing fan-out / conversation tests unaffected — they call `answer` with a specific school, and the extra national `vector_search` is harmless against their fakes)

- [ ] **Step 7: Commit**

```bash
git add ingestion/config/settings.py services/knowledge/qa_service.py tests/services/knowledge/test_qa_service.py
git commit -m "feat: weave national-scope regulations into school knowledge answers"
```

---

## Manual verification (requires Docker DB + network + Plan 2 ingest done)

After Plan 2 has ingested at least one national regulation:

```bash
docker compose up -d --wait db
.venv/bin/python - <<'PY'
from services.knowledge.qa_service import KnowledgeQAService
svc = KnowledgeQAService()
res = svc.answer("Điểm ưu tiên khu vực trong xét tuyển đại học là bao nhiêu?",
                 school="HUST", topic="admission_policy")
print("has_data:", res.has_data)
for c in res.citations:
    print(" -", c.source_url)
PY
# Expect has_data True and at least one citation pointing at datafiles.chinhphu.vn,
# even though the question was asked in HUST's scope.
```

## Done when
- A school-scoped `answer(school=X, …)` issues a second `vector_search(school="MOET", limit=KNOWLEDGE_QA_NATIONAL_TOP_K)` and merges national chunks (filtered by `min_score`, sorted by score).
- `answer(school=None, …)` and `answer(school="MOET", …)` issue **no** extra national pass.
- National sources appear in the answer's citations for school-scoped questions.
- Full suites green: `.venv/bin/python -m pytest tests/services/knowledge tests/services/chat tests/ingestion/knowledge -q`
