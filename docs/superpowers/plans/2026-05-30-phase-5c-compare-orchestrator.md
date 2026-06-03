# Phase 5c — CompareOrchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `CompareOrchestrator` that runs the advisory branch and the knowledge branch **in parallel**, normalizes each into a block (swallowing per-branch errors), and hands both to the `SynthesisAgent` — plus the reusable knowledge fan-out helpers shared with the chat layer.

**Architecture:** A small `knowledge_fanout` module loops `schools × topics`, calling the single-school `KnowledgeQAService.answer` once per pair and normalizing results into `KnowledgeBlock`s (an isolated, dependency-light helper the chat layer also reuses without importing the heavyweight graph). `CompareOrchestrator.run` fans the two branches across a `ThreadPoolExecutor`, so wall-clock ≈ `max(advisory, knowledge) + synthesis`. Each branch independently degrades to a "no data" block on error; synthesis always runs.

**Tech Stack:** Python, `concurrent.futures.ThreadPoolExecutor`, Pydantic, pytest.

**Spec:** [`../specs/2026-05-30-phase-5-hybrid-compare-agent-design.md`](../specs/2026-05-30-phase-5-hybrid-compare-agent-design.md) — CompareOrchestrator, Error handling.

**Depends on:** Phase 5a (`IntentResult.schools/topics/needs_advisory`), Phase 5b (`AdvisoryBlock`, `KnowledgeBlock`, `SynthesisAgent`).

---

### Task 1: Knowledge fan-out helpers

**Files:**
- Create: `services/chat/knowledge_fanout.py`
- Test: `tests/services/chat/test_knowledge_fanout.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/services/chat/test_knowledge_fanout.py`:

```python
from services.chat.intent_router import IntentResult
from services.chat.knowledge_fanout import run_knowledge_fanout, format_knowledge_blocks
from services.knowledge.models import Citation, KnowledgeQAResult


class FakeKnowledgeQA:
    def __init__(self, by_school=None, raise_for=None):
        # by_school: {school: KnowledgeQAResult}; default → no-data
        self._by_school = by_school or {}
        self._raise_for = raise_for or set()
        self.calls = []

    def answer(self, question, school, topic, conversation_context=""):
        self.calls.append({"question": question, "school": school, "topic": topic})
        if school in self._raise_for:
            raise RuntimeError("boom")
        return self._by_school.get(school, KnowledgeQAResult(has_data=False, confidence=0.0))


def test_fanout_calls_once_per_school_topic_pair():
    qa = FakeKnowledgeQA()
    intent = IntentResult(route="HYBRID", schools=["VNU-UET", "HUST"], topics=["tuition"])
    blocks = run_knowledge_fanout(qa, intent, "so sánh học phí", school_fallback=None)
    assert len(qa.calls) == 2
    assert {c["school"] for c in qa.calls} == {"VNU-UET", "HUST"}
    assert all(c["topic"] == "tuition" for c in qa.calls)
    assert len(blocks) == 2


def test_fanout_maps_has_data_result_into_block_with_sources():
    qa = FakeKnowledgeQA(by_school={"VNU-UET": KnowledgeQAResult(
        has_data=True, answer="35 triệu/năm",
        citations=[Citation(source_url="https://uet/hp", chunk_text="...")], confidence=0.9,
    )})
    intent = IntentResult(route="HYBRID", schools=["VNU-UET"], topics=["tuition"])
    blocks = run_knowledge_fanout(qa, intent, "học phí", school_fallback=None)
    assert blocks[0].has_data is True
    assert blocks[0].answer == "35 triệu/năm"
    assert blocks[0].school == "VNU-UET"
    assert blocks[0].sources == ["https://uet/hp"]


def test_fanout_failed_call_becomes_no_data_block_others_survive():
    qa = FakeKnowledgeQA(
        by_school={"HUST": KnowledgeQAResult(has_data=True, answer="24 triệu", citations=[], confidence=0.8)},
        raise_for={"VNU-UET"},
    )
    intent = IntentResult(route="HYBRID", schools=["VNU-UET", "HUST"], topics=["tuition"])
    blocks = run_knowledge_fanout(qa, intent, "q", school_fallback=None)
    by_school = {b.school: b for b in blocks}
    assert by_school["VNU-UET"].has_data is False
    assert by_school["HUST"].has_data is True


def test_fanout_falls_back_to_singular_then_school_fallback():
    qa = FakeKnowledgeQA()
    # no schools/topics lists, singular school present
    intent = IntentResult(route="HYBRID", school="NEU", topic="tuition")
    blocks = run_knowledge_fanout(qa, intent, "q", school_fallback="IGNORED")
    assert qa.calls[0]["school"] == "NEU"
    # no schools/topics/singular school → use school_fallback
    qa2 = FakeKnowledgeQA()
    intent2 = IntentResult(route="HYBRID", topics=["tuition"])
    run_knowledge_fanout(qa2, intent2, "q", school_fallback="VNU-UET")
    assert qa2.calls[0]["school"] == "VNU-UET"


def test_format_knowledge_blocks_renders_data_and_fallback():
    from services.chat.hybrid_models import KnowledgeBlock
    has = [KnowledgeBlock(school="VNU-UET", topic="tuition", has_data=True, answer="35 triệu",
                          sources=["https://uet/hp"])]
    out = format_knowledge_blocks(has)
    assert "35 triệu" in out
    assert "https://uet/hp" in out

    empty = [KnowledgeBlock(school="VNU-UET", topic="tuition", has_data=False)]
    out2 = format_knowledge_blocks(empty)
    assert "chưa có dữ liệu" in out2.lower()
    assert "liên hệ" in out2.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/services/chat/test_knowledge_fanout.py -v`
Expected: FAIL — `ModuleNotFoundError: services.chat.knowledge_fanout`.

- [ ] **Step 3: Implement the helpers**

Create `services/chat/knowledge_fanout.py`:

```python
from services.chat.hybrid_models import KnowledgeBlock


def _resolve_schools(intent, school_fallback):
    if intent.schools:
        return list(intent.schools)
    if intent.school:
        return [intent.school]
    if school_fallback:
        return [school_fallback]
    return [None]


def _resolve_topics(intent):
    if intent.topics:
        return list(intent.topics)
    if intent.topic:
        return [intent.topic]
    return [None]


def run_knowledge_fanout(knowledge_qa, intent, content, school_fallback=None) -> list:
    """Call the single-school KnowledgeQA once per (school, topic) pair.

    Each call swallows its own error → a no-data KnowledgeBlock; siblings survive.
    """
    blocks = []
    for school in _resolve_schools(intent, school_fallback):
        for topic in _resolve_topics(intent):
            try:
                result = knowledge_qa.answer(
                    question=content, school=school, topic=topic, conversation_context="",
                )
            except Exception:
                result = None
            if result is not None and result.has_data and result.answer:
                sources = [c.source_url for c in result.citations if c.source_url]
                blocks.append(KnowledgeBlock(
                    school=school, topic=topic, has_data=True,
                    answer=result.answer, sources=sources,
                ))
            else:
                blocks.append(KnowledgeBlock(school=school, topic=topic, has_data=False))
    return blocks


def format_knowledge_blocks(blocks) -> str:
    """Deterministic rendering of knowledge blocks for the inline (no-synthesis) path."""
    lines = []
    for block in blocks:
        if block.has_data and block.answer:
            label = block.school or ""
            body = f"{label}: {block.answer}" if label else block.answer
            if block.sources:
                body += "\n" + "\n".join(f"- {url}" for url in block.sources)
            lines.append(body)
    if not lines:
        return (
            "Hệ thống chưa có dữ liệu cho thông tin bạn hỏi. "
            "Bạn có thể liên hệ trực tiếp nhà trường để biết thêm chi tiết."
        )
    return "\n\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/services/chat/test_knowledge_fanout.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/chat/knowledge_fanout.py tests/services/chat/test_knowledge_fanout.py
git commit -m "feat(hybrid): knowledge fan-out + deterministic block formatter"
```

---

### Task 2: `CompareOrchestrator` — advisory normalization + parallel run + synthesis

**Files:**
- Create: `services/chat/compare_orchestrator.py`
- Test: `tests/services/chat/test_compare_orchestrator.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/services/chat/test_compare_orchestrator.py`:

```python
import time

from agents.models import Evidence
from services.chat.compare_orchestrator import CompareOrchestrator
from services.chat.hybrid_models import AdvisoryBlock
from services.chat.intent_router import IntentResult
from services.chat.models import ChatProfileState
from services.knowledge.models import Citation, KnowledgeQAResult


class FakeKnowledgeQA:
    def __init__(self, by_school=None, delay=0.0):
        self._by_school = by_school or {}
        self._delay = delay
        self.calls = []

    def answer(self, question, school, topic, conversation_context=""):
        self.calls.append({"school": school, "topic": topic})
        if self._delay:
            time.sleep(self._delay)
        return self._by_school.get(school, KnowledgeQAResult(has_data=False, confidence=0.0))


class RecordingSynthesis:
    def __init__(self):
        self.advisory = None
        self.knowledge = None
        self.calls = 0

    def synthesize(self, advisory, knowledge, question):
        self.calls += 1
        self.advisory = advisory
        self.knowledge = knowledge
        return "SYNTH"


def _intent(**kw):
    base = {"route": "HYBRID", "schools": ["VNU-UET"], "topics": ["tuition"], "needs_advisory": True}
    base.update(kw)
    return IntentResult(**base)


def test_run_calls_both_branches_and_synthesizes():
    qa = FakeKnowledgeQA(by_school={"VNU-UET": KnowledgeQAResult(
        has_data=True, answer="35 triệu",
        citations=[Citation(source_url="https://uet/hp", chunk_text="..")], confidence=0.9,
    )})
    synth = RecordingSynthesis()
    runner = lambda profile_state, content, trace_run_id=None: {
        "final_answer": "Tư vấn UET", "citations": [Evidence(
            source_url="https://uet/diem", school_name="VNU-UET", admission_year=2026, field_name="benchmark",
        )],
    }
    orch = CompareOrchestrator(advisory_runner=runner, knowledge_qa=qa, synthesis_agent=synth)
    out = orch.run(_intent(), ChatProfileState(total_score=25.0), "so sánh", trace_run_id=1)
    assert out == "SYNTH"
    assert synth.calls == 1
    assert synth.advisory.has_data is True
    assert "Tư vấn UET" == synth.advisory.answer
    assert synth.advisory.sources == ["https://uet/diem"]
    assert synth.knowledge[0].has_data is True


def test_run_skips_advisory_when_needs_advisory_false():
    qa = FakeKnowledgeQA()
    synth = RecordingSynthesis()
    called = {"advisory": False}

    def runner(profile_state, content, trace_run_id=None):
        called["advisory"] = True
        return {"final_answer": "x"}

    orch = CompareOrchestrator(advisory_runner=runner, knowledge_qa=qa, synthesis_agent=synth)
    orch.run(_intent(needs_advisory=False, schools=["VNU-UET", "HUST"]), ChatProfileState(), "q")
    assert called["advisory"] is False
    assert synth.advisory.has_data is False
    assert len(qa.calls) == 2  # fan-out still ran


def test_run_advisory_error_degrades_to_no_data_block():
    qa = FakeKnowledgeQA(by_school={"VNU-UET": KnowledgeQAResult(has_data=True, answer="35 triệu", citations=[], confidence=0.9)})
    synth = RecordingSynthesis()

    def runner(profile_state, content, trace_run_id=None):
        raise RuntimeError("graph blew up")

    orch = CompareOrchestrator(advisory_runner=runner, knowledge_qa=qa, synthesis_agent=synth)
    orch.run(_intent(), ChatProfileState(), "q")
    assert synth.advisory.has_data is False        # advisory degraded
    assert synth.knowledge[0].has_data is True      # knowledge unaffected


def test_run_advisory_empty_answer_is_no_data():
    qa = FakeKnowledgeQA()
    synth = RecordingSynthesis()
    runner = lambda profile_state, content, trace_run_id=None: {"final_answer": "", "advisory": ""}
    orch = CompareOrchestrator(advisory_runner=runner, knowledge_qa=qa, synthesis_agent=synth)
    orch.run(_intent(), ChatProfileState(), "q")
    assert synth.advisory.has_data is False


def test_run_executes_branches_in_parallel():
    # advisory sleeps 0.3s, knowledge sleeps 0.3s; parallel ⇒ well under the 0.6s sum.
    qa = FakeKnowledgeQA(delay=0.3)
    synth = RecordingSynthesis()

    def runner(profile_state, content, trace_run_id=None):
        time.sleep(0.3)
        return {"final_answer": "adv"}

    orch = CompareOrchestrator(advisory_runner=runner, knowledge_qa=qa, synthesis_agent=synth)
    start = time.perf_counter()
    orch.run(_intent(), ChatProfileState(), "q")
    elapsed = time.perf_counter() - start
    assert elapsed < 0.55  # max(0.3, 0.3)+overhead, not 0.6
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/services/chat/test_compare_orchestrator.py -v`
Expected: FAIL — `ModuleNotFoundError: services.chat.compare_orchestrator`.

- [ ] **Step 3: Implement the orchestrator**

Create `services/chat/compare_orchestrator.py`:

```python
from concurrent.futures import ThreadPoolExecutor

from services.chat.advisory_runner import run_advisory_for_session
from services.chat.hybrid_models import AdvisoryBlock
from services.chat.knowledge_fanout import run_knowledge_fanout
from services.chat.synthesis_agent import SynthesisAgent
from services.knowledge.qa_service import KnowledgeQAService


def _evidence_url(evidence):
    if isinstance(evidence, dict):
        return evidence.get("source_url")
    return getattr(evidence, "source_url", None)


class CompareOrchestrator:
    def __init__(self, advisory_runner=None, knowledge_qa=None, synthesis_agent=None):
        self.advisory_runner = advisory_runner or run_advisory_for_session
        self.knowledge_qa = knowledge_qa or KnowledgeQAService()
        self.synthesis_agent = synthesis_agent or SynthesisAgent()

    def run(self, intent, profile_state, content, trace_run_id=None) -> str:
        school_fallback = (
            profile_state.preferred_schools[0] if profile_state.preferred_schools else None
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            adv_future = (
                executor.submit(self._run_advisory, profile_state, content, trace_run_id)
                if intent.needs_advisory
                else None
            )
            kqa_future = executor.submit(
                run_knowledge_fanout, self.knowledge_qa, intent, content, school_fallback
            )
            advisory = self._collect_advisory(adv_future)
            knowledge = self._collect_knowledge(kqa_future)
        return self.synthesis_agent.synthesize(advisory, knowledge, content)

    def _run_advisory(self, profile_state, content, trace_run_id) -> AdvisoryBlock:
        result = self.advisory_runner(profile_state, content, trace_run_id=trace_run_id)
        answer = (result.get("final_answer") or result.get("advisory") or "").strip()
        if not answer:
            return AdvisoryBlock(has_data=False)
        sources = []
        for evidence in (result.get("citations") or []):
            url = _evidence_url(evidence)
            if url and url not in sources:
                sources.append(url)
        return AdvisoryBlock(has_data=True, answer=answer, sources=sources)

    @staticmethod
    def _collect_advisory(future) -> AdvisoryBlock:
        if future is None:
            return AdvisoryBlock(has_data=False)
        try:
            return future.result()
        except Exception:
            return AdvisoryBlock(has_data=False)

    @staticmethod
    def _collect_knowledge(future) -> list:
        try:
            return future.result()
        except Exception:
            return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/services/chat/test_compare_orchestrator.py -v`
Expected: PASS — including the parallelism timing test.

- [ ] **Step 5: Commit**

```bash
git add services/chat/compare_orchestrator.py tests/services/chat/test_compare_orchestrator.py
git commit -m "feat(hybrid): CompareOrchestrator runs both branches in parallel + synthesizes"
```

---

## Self-Review

- **Spec coverage:** "two branches in parallel, latency ≈ max" → Task 2 ThreadPoolExecutor + timing test. "each branch swallows its own error" → `_collect_advisory`/`_collect_knowledge` + per-call `try` in fan-out, with tests. "`needs_advisory=false` → skip advisory" → Task 2 test. "fan-out over schools × topics" → Task 1. Advisory citations merged via `Evidence.source_url` → `_evidence_url` (handles object or dict).
- **Placeholder scan:** None.
- **Type consistency:** `run(intent, profile_state, content, trace_run_id=None) -> str` is what Phase 5e's `HybridDispatcher` calls. `advisory_runner(profile_state, content, trace_run_id=...)` matches `run_advisory_for_session`'s signature. `synthesis_agent.synthesize(advisory, knowledge, content)` matches Phase 5b. `run_knowledge_fanout(knowledge_qa, intent, content, school_fallback)` matches Task 1 and Phase 5d's usage.
