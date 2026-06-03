# Phase 4b — KnowledgeQAService (RAG pipeline) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `KnowledgeQAService.answer()` — the RAG pipeline that embeds a query, retrieves chunks, gates on a confidence threshold, and generates a grounded, cited answer (or "no data") without ever fabricating.

**Architecture:** A single self-contained service in `services/knowledge/qa_service.py`, fully dependency-injected (`chunk_repository`, `embedder`, `gateway`) with lazy production defaults. The pipeline is: embed query (`RETRIEVAL_QUERY`) → `vector_search` (metadata pre-filter, no reranker) → threshold gate (skip the LLM below `min_score`) → JSON generation `{answer, used_source_ids}` → resolve citations (LLM-marked, with deterministic fallback). Built across three TDD tasks that each add a real code path.

**Tech Stack:** Python, Pydantic v2, pytest, Gemini via the inference gateway, pgvector cosine.

**Depends on:** Phase 4a (the `Citation` / `KnowledgeQAResult` models, the `KNOWLEDGE_QA_TOP_K` / `KNOWLEDGE_QA_MIN_SCORE` settings, the embedder `task_type` param, and the `knowledge_qa_agent` policy). Complete 4a first.

> **Commit policy for this repo:** Do NOT run `git commit`. Each task ends at a checkpoint; the user reviews and commits manually.

**Spec:** `docs/superpowers/specs/2026-05-30-phase-4-knowledge-qa-rag-agent-design.md`

---

### Task 1: Service skeleton — embedding, retrieval, threshold gate, basic generation

This task delivers `answer()` end-to-end with a *simple* citation strategy (cite every passed chunk). Tasks 2 and 3 refine citations and degradation.

**Files:**
- Create: `services/knowledge/qa_service.py`
- Test: `tests/services/knowledge/test_qa_service.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/services/knowledge/test_qa_service.py`:

```python
from services.inference.models import InferenceError, InferenceResult
from services.knowledge.models import ScoredChunk
from services.knowledge.qa_service import KnowledgeQAService


class FakeEmbedder:
    def __init__(self, vector=None):
        self.calls = []
        self._vector = vector or [0.1, 0.2, 0.3]

    def embed(self, texts, task_type="RETRIEVAL_DOCUMENT"):
        self.calls.append({"texts": list(texts), "task_type": task_type})
        return [list(self._vector) for _ in texts]


class FakeChunkRepo:
    def __init__(self, chunks):
        self._chunks = chunks
        self.calls = []

    def vector_search(self, embedding, school=None, topic=None, limit=5):
        self.calls.append(
            {"embedding": embedding, "school": school, "topic": topic, "limit": limit}
        )
        return list(self._chunks)


class FakeGateway:
    def __init__(self, parsed_data=None, raise_exc=False):
        self.calls = []
        self._parsed = parsed_data
        self._raise = raise_exc

    def run(self, request):
        self.calls.append(request)
        if self._raise:
            raise InferenceError("simulated generation failure")
        return InferenceResult(
            agent_name=request.agent_name,
            model="test-model",
            provider="test",
            content="{}",
            parsed_data=self._parsed,
        )


def _chunk(text, url, score, school="VNU-UET", topic="tuition"):
    return ScoredChunk(
        school=school, topic=topic, chunk_text=text, source_url=url, score=score
    )


def _build(chunks, parsed_data=None, raise_exc=False, vector=None, min_score=0.5, top_k=5):
    embedder = FakeEmbedder(vector=vector)
    repo = FakeChunkRepo(chunks)
    gateway = FakeGateway(parsed_data=parsed_data, raise_exc=raise_exc)
    service = KnowledgeQAService(
        chunk_repository=repo,
        embedder=embedder,
        gateway=gateway,
        min_score=min_score,
        top_k=top_k,
    )
    return service, embedder, repo, gateway


# ─── threshold gate ──────────────────────────────────────────────────────────

def test_no_chunks_returns_no_data_without_calling_gateway():
    service, _, _, gateway = _build([])
    res = service.answer("học phí bao nhiêu", school="VNU-UET", topic="tuition")
    assert res.has_data is False
    assert res.answer is None
    assert res.confidence == 0.0
    assert gateway.calls == []


def test_below_threshold_returns_no_data_without_calling_gateway():
    chunks = [_chunk("Học phí 35 triệu", "http://uet/a", score=0.3)]
    service, _, _, gateway = _build(chunks, parsed_data={"answer": "x"}, min_score=0.5)
    res = service.answer("học phí bao nhiêu", "VNU-UET", "tuition")
    assert res.has_data is False
    assert res.confidence == 0.3
    assert gateway.calls == []


# ─── embedding + retrieval wiring ────────────────────────────────────────────

def test_query_embedded_with_retrieval_query_task_type():
    chunks = [_chunk("Học phí 35 triệu", "http://uet/a", score=0.9)]
    service, embedder, _, _ = _build(
        chunks, parsed_data={"answer": "Học phí 35 triệu/năm."}
    )
    service.answer("học phí bao nhiêu", "VNU-UET", "tuition")
    assert embedder.calls[0]["texts"] == ["học phí bao nhiêu"]
    assert embedder.calls[0]["task_type"] == "RETRIEVAL_QUERY"


def test_metadata_filters_passed_to_vector_search():
    chunks = [_chunk("x", "u", score=0.9)]
    service, _, repo, _ = _build(chunks, parsed_data={"answer": "ok"}, top_k=5)
    service.answer("q", "VNU-UET", "tuition")
    assert repo.calls[0]["school"] == "VNU-UET"
    assert repo.calls[0]["topic"] == "tuition"
    assert repo.calls[0]["limit"] == 5


# ─── basic generation (citations refined in Task 2) ──────────────────────────

def test_above_threshold_returns_grounded_answer_with_confidence():
    chunks = [
        _chunk("Học phí 35 triệu/năm", "http://uet/a", score=0.92),
        _chunk("Thông tin khác", "http://uet/b", score=0.71),
    ]
    service, _, _, gateway = _build(
        chunks, parsed_data={"answer": "Học phí khoảng 35 triệu/năm."}
    )
    res = service.answer("học phí bao nhiêu", "VNU-UET", "tuition")
    assert res.has_data is True
    assert res.answer == "Học phí khoảng 35 triệu/năm."
    assert res.confidence == 0.92
    assert len(gateway.calls) == 1
    # No used_source_ids in the response → cite every passed chunk.
    assert len(res.citations) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/services/knowledge/test_qa_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.knowledge.qa_service'`

- [ ] **Step 3: Write minimal implementation**

Create `services/knowledge/qa_service.py`:

```python
from typing import Optional

from ingestion.config.settings import KNOWLEDGE_QA_MIN_SCORE, KNOWLEDGE_QA_TOP_K
from ingestion.knowledge.embedder import GeminiEmbedder
from services import build_default_gateway
from services.inference.models import InferenceRequest
from services.knowledge.models import Citation, KnowledgeQAResult
from services.knowledge.repository import KnowledgeChunkRepository

KNOWLEDGE_QA_SYSTEM_PROMPT = """
Bạn là trợ lý trả lời câu hỏi về thông tin tuyển sinh đại học Việt Nam,
chỉ dựa trên các đoạn văn bản được cung cấp.

Quy tắc bắt buộc:
- Chỉ trả lời dựa trên các đoạn văn bản tham khảo được đánh số bên dưới.
- Tuyệt đối không suy diễn hay bổ sung thông tin ngoài các đoạn đó.
- Nếu các đoạn không đủ thông tin để trả lời, để "answer" là chuỗi rỗng "".
- Trả lời ngắn gọn, đúng trọng tâm, bằng tiếng Việt.

Trả về JSON hợp lệ, không giải thích thêm:
{"answer": "<câu trả lời hoặc chuỗi rỗng>", "used_source_ids": [<số thứ tự các đoạn đã dùng>]}
""".strip()


class KnowledgeQAService:
    def __init__(
        self,
        chunk_repository=None,
        embedder=None,
        gateway=None,
        top_k: int = KNOWLEDGE_QA_TOP_K,
        min_score: float = KNOWLEDGE_QA_MIN_SCORE,
    ):
        self._chunk_repository = chunk_repository or KnowledgeChunkRepository()
        self._embedder = embedder or GeminiEmbedder()
        self._gateway = gateway or build_default_gateway()
        self._top_k = top_k
        self._min_score = min_score

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
        confidence = chunks[0].score if chunks else 0.0
        if not chunks or confidence < self._min_score:
            return KnowledgeQAResult(has_data=False, confidence=confidence)
        return self._generate(question, chunks, confidence, conversation_context)

    def _generate(self, question, chunks, confidence, conversation_context) -> KnowledgeQAResult:
        result = self._gateway.run(
            InferenceRequest(
                agent_name="knowledge_qa_agent",
                task_type="knowledge_qa",
                system_prompt=KNOWLEDGE_QA_SYSTEM_PROMPT,
                user_prompt=self._build_user_prompt(question, chunks, conversation_context),
                output_mode="json",
                temperature=0.0,
            )
        )
        data = result.parsed_data or {}
        answer_text = str(data.get("answer") or "").strip()
        citations = [
            Citation(source_url=chunk.source_url or "", chunk_text=chunk.chunk_text)
            for chunk in chunks
        ]
        return KnowledgeQAResult(
            has_data=True,
            answer=answer_text,
            citations=citations,
            confidence=confidence,
        )

    @staticmethod
    def _build_user_prompt(question, chunks, conversation_context) -> str:
        lines = []
        if conversation_context:
            lines.append(f"Ngữ cảnh hội thoại trước đó:\n{conversation_context}\n")
        lines.append("Các đoạn văn bản tham khảo (đánh số):")
        for i, chunk in enumerate(chunks, start=1):
            lines.append(f"[{i}] {chunk.chunk_text}")
        lines.append(f"\nCâu hỏi: {question}")
        return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/services/knowledge/test_qa_service.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Checkpoint (do NOT commit)**

Do NOT run `git commit`. Stop here for the user to review.

---

### Task 2: Precise citations from `used_source_ids` (with deterministic fallback + dedup)

**Files:**
- Modify: `services/knowledge/qa_service.py` (`_generate` citation line + new `_resolve_citations`)
- Test: `tests/services/knowledge/test_qa_service.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/services/knowledge/test_qa_service.py`:

```python
def test_citations_limited_to_used_source_ids():
    chunks = [
        _chunk("Học phí 35 triệu/năm", "http://uet/a", score=0.92),
        _chunk("Ký túc xá", "http://uet/b", score=0.71),
    ]
    service, _, _, _ = _build(
        chunks, parsed_data={"answer": "Học phí 35 triệu.", "used_source_ids": [1]}
    )
    res = service.answer("học phí bao nhiêu", "VNU-UET", "tuition")
    assert len(res.citations) == 1
    assert res.citations[0].source_url == "http://uet/a"
    assert res.citations[0].chunk_text == "Học phí 35 triệu/năm"


def test_citations_fallback_to_all_chunks_when_used_ids_empty():
    chunks = [_chunk("a", "http://uet/a", 0.9), _chunk("b", "http://uet/b", 0.8)]
    service, _, _, _ = _build(
        chunks, parsed_data={"answer": "ans", "used_source_ids": []}
    )
    res = service.answer("q", "VNU-UET", "tuition")
    assert len(res.citations) == 2


def test_citations_fallback_when_used_ids_invalid():
    chunks = [_chunk("a", "http://uet/a", 0.9)]
    service, _, _, _ = _build(
        chunks, parsed_data={"answer": "ans", "used_source_ids": [99, "x"]}
    )
    res = service.answer("q", "VNU-UET", "tuition")
    assert len(res.citations) == 1
    assert res.citations[0].source_url == "http://uet/a"


def test_citations_deduped_by_source_url():
    chunks = [
        _chunk("đoạn 1", "http://uet/same", 0.9),
        _chunk("đoạn 2", "http://uet/same", 0.8),
    ]
    service, _, _, _ = _build(
        chunks, parsed_data={"answer": "ans", "used_source_ids": [1, 2]}
    )
    res = service.answer("q", "VNU-UET", "tuition")
    assert len(res.citations) == 1
    assert res.citations[0].source_url == "http://uet/same"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/services/knowledge/test_qa_service.py -k "used_source_ids or deduped" -v`
Expected: FAIL — `test_citations_limited_to_used_source_ids` and `test_citations_deduped_by_source_url` get 2 citations (Task 1 cites all chunks)

- [ ] **Step 3: Write minimal implementation**

In `services/knowledge/qa_service.py`, replace the citation list-comprehension in `_generate` with a call to a new helper:

```python
        data = result.parsed_data or {}
        answer_text = str(data.get("answer") or "").strip()
        citations = self._resolve_citations(chunks, data.get("used_source_ids"))
        return KnowledgeQAResult(
            has_data=True,
            answer=answer_text,
            citations=citations,
            confidence=confidence,
        )

    @staticmethod
    def _resolve_citations(chunks, used_source_ids) -> list:
        ids = used_source_ids if isinstance(used_source_ids, list) else []
        selected = [
            chunks[i - 1]
            for i in ids
            if isinstance(i, int) and 1 <= i <= len(chunks)
        ]
        if not selected:
            selected = list(chunks)  # deterministic fallback: cite every passed chunk

        citations = []
        seen = set()
        for chunk in selected:
            url = chunk.source_url or ""
            key = url if url else ("", chunk.chunk_text)  # don't collapse distinct unsourced chunks
            if key in seen:
                continue
            seen.add(key)
            citations.append(Citation(source_url=url, chunk_text=chunk.chunk_text))
        return citations
```

(The `Citation` import is already at the top of the file from Task 1.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/services/knowledge/test_qa_service.py -v`
Expected: PASS (all 10 tests; the Task 1 `...returns_grounded_answer_with_confidence` still passes because no `used_source_ids` → fallback to all chunks → 2 citations)

- [ ] **Step 5: Checkpoint (do NOT commit)**

Do NOT run `git commit`. Stop here for the user to review.

---

### Task 3: Degrade safely when generation produces no answer / errors

**Files:**
- Modify: `services/knowledge/qa_service.py` (`_generate`: wrap gateway call, guard empty answer)
- Test: `tests/services/knowledge/test_qa_service.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/services/knowledge/test_qa_service.py`:

```python
def test_no_answer_text_degrades_to_no_data():
    chunks = [_chunk("Học phí 35 triệu", "http://uet/a", 0.92)]
    service, _, _, _ = _build(chunks, parsed_data=None)  # JSON structure failure
    res = service.answer("q", "VNU-UET", "tuition")
    assert res.has_data is False
    assert res.answer is None
    assert res.confidence == 0.92


def test_empty_answer_string_degrades_to_no_data():
    chunks = [_chunk("x", "http://uet/a", 0.92)]
    service, _, _, _ = _build(
        chunks, parsed_data={"answer": "   ", "used_source_ids": [1]}
    )
    res = service.answer("q", "VNU-UET", "tuition")
    assert res.has_data is False


def test_gateway_exception_degrades_to_no_data():
    chunks = [_chunk("x", "http://uet/a", 0.92)]
    service, _, _, gateway = _build(chunks, raise_exc=True)
    res = service.answer("q", "VNU-UET", "tuition")
    assert res.has_data is False
    assert len(gateway.calls) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/services/knowledge/test_qa_service.py -k "degrades" -v`
Expected: FAIL — `parsed_data=None` currently yields `has_data=True` with `answer=""`; `raise_exc=True` currently propagates the `InferenceError`

- [ ] **Step 3: Write minimal implementation**

In `services/knowledge/qa_service.py`, update `_generate` to wrap the gateway call and bail out when there is no usable answer text:

```python
    def _generate(self, question, chunks, confidence, conversation_context) -> KnowledgeQAResult:
        try:
            result = self._gateway.run(
                InferenceRequest(
                    agent_name="knowledge_qa_agent",
                    task_type="knowledge_qa",
                    system_prompt=KNOWLEDGE_QA_SYSTEM_PROMPT,
                    user_prompt=self._build_user_prompt(question, chunks, conversation_context),
                    output_mode="json",
                    temperature=0.0,
                )
            )
            data = result.parsed_data or {}
        except Exception:
            data = {}

        answer_text = str(data.get("answer") or "").strip()
        if not answer_text:
            # No grounded answer produced → degrade rather than fabricate.
            return KnowledgeQAResult(has_data=False, confidence=confidence)

        citations = self._resolve_citations(chunks, data.get("used_source_ids"))
        return KnowledgeQAResult(
            has_data=True,
            answer=answer_text,
            citations=citations,
            confidence=confidence,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/services/knowledge/test_qa_service.py -v`
Expected: PASS (all 13 tests)

- [ ] **Step 5: Checkpoint (do NOT commit)**

Do NOT run `git commit`. Stop here for the user to review.

---

## Phase 4b Done — Verification

```
python -m pytest tests/services/knowledge/test_qa_service.py -v
```

Expected: all PASS. `KnowledgeQAService.answer(question, school, topic, conversation_context) -> KnowledgeQAResult` is now ready to be wired into the chat flow (Phase 4c).
