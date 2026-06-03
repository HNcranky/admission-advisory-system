# Phase 4c — KnowledgeQA Chat Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `KnowledgeQAService` into `ConversationService._handle_knowledge_qa` so a `KNOWLEDGE_QA` turn returns a grounded, cited answer (with an inline `Nguồn:` list and structured `citations`), falling back to the existing "chưa có dữ liệu" message when there is no data — without ever resetting profile/flow state, and re-asking the pending advisory question mid-flow.

**Architecture:** Add `citations` to `ConversationTurnResult`, inject `knowledge_qa` into `ConversationService` (same pattern as `intent_router`), resolve `school` from the router or `preferred_schools`, render the result, and wrap the service call so any error degrades to the existing fallback. The advisory graph and all other branches are untouched.

**Tech Stack:** Python, Pydantic v2, pytest.

**Depends on:** Phase 4a + 4b complete (`Citation`, `KnowledgeQAResult`, `KnowledgeQAService`). Complete them first.

> **Commit policy for this repo:** Do NOT run `git commit`. Each task ends at a checkpoint; the user reviews and commits manually.

**Spec:** `docs/superpowers/specs/2026-05-30-phase-4-knowledge-qa-rag-agent-design.md`

---

### Task 1: Add `citations` to `ConversationTurnResult`

**Files:**
- Modify: `services/chat/models.py:1-3` (import) and `:39-43` (`ConversationTurnResult`)
- Test: `tests/services/chat/test_conversation_turn_result.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/services/chat/test_conversation_turn_result.py`:

```python
from services.chat.models import ChatProfileState, ConversationTurnResult
from services.knowledge.models import Citation


def test_conversation_turn_result_defaults_citations_empty():
    r = ConversationTurnResult(
        session_status="ready",
        assistant_message="hi",
        profile_state=ChatProfileState(),
    )
    assert r.citations == []


def test_conversation_turn_result_accepts_citations():
    r = ConversationTurnResult(
        session_status="ready",
        assistant_message="hi",
        profile_state=ChatProfileState(),
        citations=[Citation(source_url="u", chunk_text="t")],
    )
    assert len(r.citations) == 1
    assert r.citations[0].source_url == "u"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/chat/test_conversation_turn_result.py -v`
Expected: FAIL with `pydantic ... Object has no attribute 'citations'` (the field is not yet defined, so the `citations=[...]` kwarg is rejected)

- [ ] **Step 3: Write minimal implementation**

In `services/chat/models.py`, add the import near the top (after the existing `from pydantic import ...` line):

```python
from typing import Any, Dict, Optional, List

from pydantic import BaseModel, Field

from services.knowledge.models import Citation
```

Then add the `citations` field to `ConversationTurnResult`:

```python
class ConversationTurnResult(BaseModel):
    session_status: str
    assistant_message: str
    should_start_run: bool = False
    profile_state: ChatProfileState
    citations: List[Citation] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/chat/test_conversation_turn_result.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Confirm nothing else broke**

Run: `python -m pytest tests/services/chat/test_conversation_service.py -v`
Expected: PASS (the new optional field defaults to `[]`, so existing result constructions are unaffected)

- [ ] **Step 6: Checkpoint (do NOT commit)**

Do NOT run `git commit`. Stop here for the user to review.

---

### Task 2: Inject `knowledge_qa` and implement the real `_handle_knowledge_qa`

This task changes the test harness (new fake + `_make_service` arg) and the production wiring together, so the suite goes red (new tests + `TypeError`) → green in one task with no broken intermediate state.

**Files:**
- Modify: `tests/services/chat/test_conversation_service.py` (imports, new fake, `_make_service`, new tests)
- Modify: `services/chat/conversation_service.py` (imports + `__init__` + dispatch + `_handle_knowledge_qa`)

- [ ] **Step 1: Update the test harness and write the failing tests**

In `tests/services/chat/test_conversation_service.py`, add to the imports at the top:

```python
from services.knowledge.models import Citation, KnowledgeQAResult
```

Add this fake after the existing `FakeIntentRouter` class:

```python
class FakeKnowledgeQA:
    def __init__(self, result=None, raise_exc=False):
        self._result = result
        self._raise = raise_exc
        self.calls = []

    def answer(self, question, school, topic, conversation_context=""):
        self.calls.append({"question": question, "school": school, "topic": topic})
        if self._raise:
            raise RuntimeError("simulated knowledge-qa failure")
        if self._result is not None:
            return self._result
        return KnowledgeQAResult(has_data=False, confidence=0.0)
```

Update `_make_service` to accept and inject it (default `FakeKnowledgeQA()` returns `has_data=False`, preserving every existing fallback-asserting test):

```python
def _make_service(intent_result=None, profile=None, flow=None, status=None, extract=None, knowledge_qa=None):
    """Build a ConversationService backed by fakes. Returns (service, repo)."""
    repo = FakeRepository()
    if profile is not None:
        repo.profile_state = profile
    if flow is not None:
        repo.flow_state = flow
    if status is not None:
        repo.status = status
    router = FakeIntentRouter(intent_result or IntentResult(route="ADVISORY_FLOW"))
    service = ConversationService(
        repository=repo,
        extract_profile=extract or (lambda text: StudentProfile()),
        intent_router=router,
        knowledge_qa=knowledge_qa or FakeKnowledgeQA(),
    )
    return service, repo
```

Then append the new tests:

```python
# ─── Phase 4: KnowledgeQA service wiring ─────────────────────────────────────

def test_knowledge_qa_data_answer_is_surfaced_with_sources():
    qa = FakeKnowledgeQA(result=KnowledgeQAResult(
        has_data=True,
        answer="Học phí khoảng 35 triệu/năm.",
        citations=[Citation(source_url="https://uet/hoc-phi", chunk_text="Học phí 35 triệu")],
        confidence=0.9,
    ))
    service, _ = _make_service(
        intent_result=IntentResult(route="KNOWLEDGE_QA", topic="tuition", school="VNU-UET"),
        knowledge_qa=qa,
    )
    result = service.handle_user_message("tok", "học phí UET bao nhiêu")
    assert "35 triệu" in result.assistant_message
    assert "Nguồn:" in result.assistant_message
    assert "https://uet/hoc-phi" in result.assistant_message
    assert len(result.citations) == 1
    assert result.citations[0].source_url == "https://uet/hoc-phi"
    assert result.should_start_run is False


def test_knowledge_qa_data_answer_does_not_reset_profile_or_flow():
    flow = FlowState(active_flow="ADVISORY_FLOW", pending_question="Bạn học khối gì?")
    qa = FakeKnowledgeQA(result=KnowledgeQAResult(
        has_data=True, answer="Học phí 35 triệu.", citations=[], confidence=0.9,
    ))
    service, repo = _make_service(
        intent_result=IntentResult(route="KNOWLEDGE_QA", topic="tuition", school="VNU-UET"),
        profile=ChatProfileState(total_score=25.0),
        flow=flow,
        knowledge_qa=qa,
    )
    result = service.handle_user_message("tok", "học phí UET bao nhiêu")
    assert repo.flow_state == flow          # untouched
    assert repo.profile_state.total_score == 25.0
    assert "Nhân tiện" in result.assistant_message  # mid-flow re-ask still appended


def test_knowledge_qa_resolves_school_from_preferred_schools_when_intent_school_null():
    qa = FakeKnowledgeQA(result=KnowledgeQAResult(has_data=False))
    service, _ = _make_service(
        intent_result=IntentResult(route="KNOWLEDGE_QA", topic="tuition", school=None),
        profile=ChatProfileState(preferred_schools=["VNU-UET"]),
        knowledge_qa=qa,
    )
    service.handle_user_message("tok", "trường này học phí bao nhiêu")
    assert qa.calls[0]["school"] == "VNU-UET"
    assert qa.calls[0]["question"] == "trường này học phí bao nhiêu"


def test_knowledge_qa_service_error_degrades_to_fallback():
    qa = FakeKnowledgeQA(raise_exc=True)
    service, _ = _make_service(
        intent_result=IntentResult(route="KNOWLEDGE_QA", topic="tuition", school="VNU-UET"),
        knowledge_qa=qa,
    )
    result = service.handle_user_message("tok", "học phí UET bao nhiêu")
    assert "chưa có dữ liệu" in result.assistant_message
    assert result.citations == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/services/chat/test_conversation_service.py -k "knowledge_qa_data or resolves_school or service_error" -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'knowledge_qa'`

- [ ] **Step 3: Write the implementation**

In `services/chat/conversation_service.py`, add ONE new import line near the existing imports (the file already imports `ChatSessionRepository` and `IntentRouter` — only this line is new):

```python
from services.knowledge.qa_service import KnowledgeQAService
```

Update `__init__` to inject the service:

```python
    def __init__(self, repository=None, extract_profile=None, intent_router=None, knowledge_qa=None):
        self.repository = repository or ChatSessionRepository()
        self.extract_profile = extract_profile or self._extract_profile
        self.intent_router = intent_router or IntentRouter()
        self.knowledge_qa = knowledge_qa or KnowledgeQAService()
```

Update the dispatch in `handle_user_message` to pass `content`:

```python
        if intent.route in ("KNOWLEDGE_QA", "HYBRID"):
            return self._handle_knowledge_qa(session_token, content, intent, profile_state, flow_state, session_status)
```

Replace the entire `_handle_knowledge_qa` method with:

```python
    def _handle_knowledge_qa(self, session_token, content, intent, profile_state, flow_state, session_status):
        # Resolve school: router value first, else the student's top preferred school.
        school = intent.school or (
            profile_state.preferred_schools[0] if profile_state.preferred_schools else None
        )

        result = None
        try:
            result = self.knowledge_qa.answer(
                question=content,
                school=school,
                topic=intent.topic,
                conversation_context="",
            )
        except Exception:
            result = None  # any embed/LLM/DB failure → graceful fallback below

        if result is not None and result.has_data and result.answer:
            body = self._format_answer_with_sources(result.answer, result.citations)
            citations = result.citations
        else:
            topic_label = self._TOPIC_LABELS.get(intent.topic or "", "thông tin này")
            school_label = school or "trường bạn hỏi"
            body = (
                f"Hệ thống chưa có dữ liệu về {topic_label} của {school_label}. "
                f"Bạn có thể liên hệ trực tiếp nhà trường để biết thêm chi tiết."
            )
            citations = []

        response = self._append_return_prompt(body, flow_state)
        self.repository.append_message(session_token, "assistant", response, "assistant_result")
        return ConversationTurnResult(
            session_status=session_status,
            assistant_message=response,
            should_start_run=False,
            profile_state=profile_state,
            citations=citations,
        )

    @staticmethod
    def _format_answer_with_sources(answer, citations):
        urls = []
        for citation in citations:
            if citation.source_url and citation.source_url not in urls:
                urls.append(citation.source_url)
        if not urls:
            return answer
        sources = "\n".join(f"- {url}" for url in urls)
        return f"{answer}\n\nNguồn:\n{sources}"
```

- [ ] **Step 4: Run the full conversation suite**

Run: `python -m pytest tests/services/chat/test_conversation_service.py -v`
Expected: PASS — both the four new tests and every pre-existing test (the existing `KNOWLEDGE_QA` / `HYBRID` tests now route through `FakeKnowledgeQA(has_data=False)` → the same fallback text they already assert).

- [ ] **Step 5: Checkpoint (do NOT commit)**

Do NOT run `git commit`. Stop here for the user to review.

---

### Task 3: End-to-end acceptance test (mock corpus → grounded answer)

**Files:**
- Test: `tests/services/chat/test_knowledge_qa_integration.py` (create)

- [ ] **Step 1: Write the acceptance test**

Create `tests/services/chat/test_knowledge_qa_integration.py`:

```python
from types import SimpleNamespace

from agents.models import StudentProfile
from services.chat.conversation_service import ConversationService
from services.chat.intent_router import IntentResult
from services.chat.models import ChatProfileState, FlowState
from services.inference.models import InferenceResult
from services.knowledge.models import ScoredChunk
from services.knowledge.qa_service import KnowledgeQAService


class _ChatRepo:
    def __init__(self, profile, flow):
        self.profile_state = profile
        self.flow_state = flow
        self.messages = []
        self.status = "collecting_profile"

    def append_message(self, *args, **kwargs):
        self.messages.append(args)

    def get_session_by_token(self, token):
        return SimpleNamespace(session_token=token, status=self.status)

    def get_profile_state(self, token):
        return self.profile_state

    def update_profile_state(self, token, profile, status):
        self.profile_state = profile
        self.status = status

    def get_flow_state(self, token):
        return self.flow_state

    def update_flow_state(self, token, flow):
        self.flow_state = flow


class _Router:
    def __init__(self, result):
        self._result = result

    def classify(self, message, profile_state):
        return self._result


class _Embedder:
    def embed(self, texts, task_type="RETRIEVAL_DOCUMENT"):
        return [[0.1, 0.2, 0.3] for _ in texts]


class _Gateway:
    def __init__(self, parsed):
        self._parsed = parsed

    def run(self, request):
        return InferenceResult(
            agent_name=request.agent_name,
            model="test-model",
            provider="test",
            content="{}",
            parsed_data=self._parsed,
        )


class _Corpus:
    """In-memory mock corpus mimicking KnowledgeChunkRepository.vector_search."""

    def __init__(self, chunks):
        self._chunks = chunks

    def vector_search(self, embedding, school=None, topic=None, limit=5):
        matched = [
            c
            for c in self._chunks
            if (school is None or c.school == school)
            and (topic is None or c.topic == topic)
        ]
        return matched[:limit]


def _service(corpus, parsed, intent, profile=None):
    qa = KnowledgeQAService(
        chunk_repository=corpus,
        embedder=_Embedder(),
        gateway=_Gateway(parsed),
        min_score=0.5,
    )
    repo = _ChatRepo(profile or ChatProfileState(), FlowState())
    return ConversationService(
        repository=repo,
        extract_profile=lambda text: StudentProfile(),
        intent_router=_Router(intent),
        knowledge_qa=qa,
    )


def test_knowledge_qa_end_to_end_grounded_answer_with_citations():
    corpus = _Corpus([
        ScoredChunk(
            school="VNU-UET",
            topic="tuition",
            chunk_text="Học phí VNU-UET năm 2026 là 35 triệu đồng/năm.",
            source_url="https://uet.vnu.edu.vn/hoc-phi",
            score=0.93,
        ),
    ])
    service = _service(
        corpus,
        parsed={
            "answer": "Học phí VNU-UET năm 2026 là 35 triệu đồng/năm.",
            "used_source_ids": [1],
        },
        intent=IntentResult(route="KNOWLEDGE_QA", topic="tuition", school="VNU-UET"),
        profile=ChatProfileState(preferred_schools=["VNU-UET"]),
    )

    result = service.handle_user_message("tok", "Học phí VNU-UET bao nhiêu?")

    assert result.should_start_run is False
    assert "35 triệu" in result.assistant_message
    assert "https://uet.vnu.edu.vn/hoc-phi" in result.assistant_message  # Nguồn appended
    assert len(result.citations) == 1
    assert result.citations[0].source_url == "https://uet.vnu.edu.vn/hoc-phi"
    assert "Học phí" in result.citations[0].chunk_text


def test_knowledge_qa_end_to_end_below_threshold_no_fabrication():
    corpus = _Corpus([
        ScoredChunk(
            school="VNU-UET",
            topic="tuition",
            chunk_text="Một đoạn không liên quan.",
            source_url="https://uet.vnu.edu.vn/x",
            score=0.2,  # below min_score → gate trips, LLM never consulted
        ),
    ])
    service = _service(
        corpus,
        parsed={"answer": "SỐ LIỆU BỊA KHÔNG ĐƯỢC DÙNG"},
        intent=IntentResult(route="KNOWLEDGE_QA", topic="tuition", school="VNU-UET"),
    )

    result = service.handle_user_message("tok", "Học phí bao nhiêu?")

    assert "chưa có dữ liệu" in result.assistant_message
    assert result.citations == []
    assert "BỊA" not in result.assistant_message
```

- [ ] **Step 2: Run the acceptance test**

Run: `python -m pytest tests/services/chat/test_knowledge_qa_integration.py -v`
Expected: PASS (2 tests)

- [ ] **Step 3: Checkpoint (do NOT commit)**

Do NOT run `git commit`. Stop here for the user to review.

---

## Phase 4c Done — Full Verification

Run the entire Phase 4 surface plus the existing chat/knowledge suites to confirm no regressions:

```
python -m pytest tests/services/chat tests/services/knowledge tests/services/inference/test_factory.py tests/ingestion/knowledge/test_embedder.py tests/ingestion/test_knowledge_qa_settings.py -v
```

Expected: all PASS.

### Acceptance criteria mapping (from the spec)

- `"Học phí VNU-UET bao nhiêu?"` → cited answer → `test_knowledge_qa_end_to_end_grounded_answer_with_citations`
- Topic with no data → clear fallback, no invented figures → `test_knowledge_qa_end_to_end_below_threshold_no_fabrication`, `test_knowledge_qa_service_error_degrades_to_fallback`
- `citations` carry `source_url` + `chunk_text` → integration test asserts both
- Confidence `< threshold` → auto fallback, no generation → `test_below_threshold_returns_no_data_without_calling_gateway` (4b) + integration below-threshold test
- `school` resolved from context → `test_knowledge_qa_resolves_school_from_preferred_schools_when_intent_school_null`
- Integration test: mock corpus → grounded answer → `test_knowledge_qa_integration.py`
- Profile/flow not reset on a KnowledgeQA turn → `test_knowledge_qa_data_answer_does_not_reset_profile_or_flow`

> **Response-time (<5s p95)** is a property of the real Gemini calls (1 embed + at most 1 generate) and is not asserted in unit tests. Validate manually against a live corpus once Phase 3 data is ingested.
