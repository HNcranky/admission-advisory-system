# Phase 5b — SynthesisAgent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `SynthesisAgent` that merges one advisory block and a list of knowledge blocks into a single Vietnamese markdown answer with two clearly-labelled sections and a merged, deduped source list — grounded (never adds facts) and resilient (deterministic fallback when the LLM fails).

**Architecture:** Introduce shared Pydantic carriers (`AdvisoryBlock`, `KnowledgeBlock`) so the orchestrator (Phase 5c) and synthesis agent share one vocabulary without import cycles. `SynthesisAgent.synthesize()` makes one grounding-strict `free_text` gateway call, then deterministically appends merged sources; on any LLM failure it concatenates the blocks verbatim. Sources are always assembled in code (not trusted to the LLM) so they can never be hallucinated.

**Tech Stack:** Python, Pydantic, pytest. LLM gateway via `services/inference` (`free_text` mode → `InferenceResult.content`).

**Spec:** [`../specs/2026-05-30-phase-5-hybrid-compare-agent-design.md`](../specs/2026-05-30-phase-5-hybrid-compare-agent-design.md) — decision 6, SynthesisAgent + Merged citations.

---

### Task 1: Shared hybrid carrier models

**Files:**
- Create: `services/chat/hybrid_models.py`
- Test: `tests/services/chat/test_hybrid_models.py`

- [ ] **Step 1: Write the failing test**

Create `tests/services/chat/test_hybrid_models.py`:

```python
from services.chat.hybrid_models import AdvisoryBlock, KnowledgeBlock


def test_advisory_block_defaults():
    b = AdvisoryBlock()
    assert b.has_data is False
    assert b.answer is None
    assert b.sources == []


def test_knowledge_block_defaults():
    b = KnowledgeBlock()
    assert b.has_data is False
    assert b.school is None
    assert b.topic is None
    assert b.answer is None
    assert b.sources == []


def test_knowledge_block_full():
    b = KnowledgeBlock(
        school="VNU-UET", topic="tuition", has_data=True,
        answer="35 triệu/năm", sources=["https://uet/hp"],
    )
    assert b.school == "VNU-UET"
    assert b.has_data is True
    assert b.sources == ["https://uet/hp"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/chat/test_hybrid_models.py -v`
Expected: FAIL — `ModuleNotFoundError: services.chat.hybrid_models`.

- [ ] **Step 3: Create the models**

Create `services/chat/hybrid_models.py`:

```python
from typing import List, Optional

from pydantic import BaseModel, Field


class AdvisoryBlock(BaseModel):
    """The advisory branch result, normalized for synthesis."""
    has_data: bool = False
    answer: Optional[str] = None
    sources: List[str] = Field(default_factory=list)


class KnowledgeBlock(BaseModel):
    """One (school, topic) knowledge result, normalized for synthesis."""
    school: Optional[str] = None
    topic: Optional[str] = None
    has_data: bool = False
    answer: Optional[str] = None
    sources: List[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/chat/test_hybrid_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/chat/hybrid_models.py tests/services/chat/test_hybrid_models.py
git commit -m "feat(hybrid): add AdvisoryBlock/KnowledgeBlock carrier models"
```

---

### Task 2: Register `synthesis_agent` in the inference factory

**Files:**
- Modify: `services/inference/factory.py` (the `agent_overrides` dict, ~lines 9-37)
- Test: `tests/services/inference/test_factory.py` (create if absent)

- [ ] **Step 1: Write the failing test**

Create or extend `tests/services/inference/test_factory.py`:

```python
from services.inference.factory import build_default_gateway


def test_synthesis_agent_is_registered():
    gateway = build_default_gateway()
    policy = gateway.registry.resolve("synthesis_agent")
    assert policy.primary_model == "gemini-2.5-flash"
    assert policy.output_mode == "free_text"
    assert policy.allow_fallback is True
    assert policy.fallback_model == "gemini-2.5-flash-lite"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/inference/test_factory.py::test_synthesis_agent_is_registered -v`
Expected: FAIL — `synthesis_agent` resolves to the default policy (`primary_model` is the registry default `gemini-2.5-flash-lite`, not `gemini-2.5-flash`).

- [ ] **Step 3: Register the override**

In `services/inference/factory.py`, add this entry inside `agent_overrides`, right after the `"knowledge_qa_agent"` block:

```python
            "synthesis_agent": {
                "primary_model": "gemini-2.5-flash",
                "output_mode": "free_text",
                "max_retries": 1,
                "allow_fallback": True,
                "fallback_model": "gemini-2.5-flash-lite",
            },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/inference/test_factory.py::test_synthesis_agent_is_registered -v`
Expected: PASS. (`ModelRegistry.resolve` returns an `InferencePolicy` exposing `primary_model`, `fallback_model`, `allow_fallback`, `output_mode`, `max_retries`.)

- [ ] **Step 5: Commit**

```bash
git add services/inference/factory.py tests/services/inference/test_factory.py
git commit -m "feat(inference): register synthesis_agent (flash, free_text, flash-lite fallback)"
```

---

### Task 3: `SynthesisAgent` — deterministic source merge + fallback concatenation

**Files:**
- Create: `services/chat/synthesis_agent.py`
- Test: `tests/services/chat/test_synthesis_agent.py`

We build the deterministic parts first (source merge, fallback concatenation), then the LLM path in Task 4. This keeps each step independently testable.

- [ ] **Step 1: Write the failing tests**

Create `tests/services/chat/test_synthesis_agent.py`:

```python
from services.chat.hybrid_models import AdvisoryBlock, KnowledgeBlock
from services.chat.synthesis_agent import SynthesisAgent


class FailingGateway:
    """Forces the deterministic fallback path."""
    def is_available(self):
        return True

    def run(self, request):
        raise RuntimeError("synthesis llm down")


def _agent_with_failing_gateway():
    return SynthesisAgent(gateway=FailingGateway())


def test_fallback_concatenation_has_both_sections():
    agent = _agent_with_failing_gateway()
    advisory = AdvisoryBlock(has_data=True, answer="Bạn có khả năng đậu UET ngành CNTT.")
    knowledge = [KnowledgeBlock(school="VNU-UET", topic="tuition", has_data=True, answer="Học phí ~35 triệu/năm.")]
    out = agent.synthesize(advisory, knowledge, "so sánh")
    assert "Theo dữ liệu tuyển sinh" in out
    assert "Thông tin trường" in out
    assert "khả năng đậu UET" in out
    assert "35 triệu" in out


def test_fallback_states_missing_advisory():
    agent = _agent_with_failing_gateway()
    advisory = AdvisoryBlock(has_data=False)
    knowledge = [KnowledgeBlock(school="HUST", topic="tuition", has_data=True, answer="Học phí HUST ~24 triệu.")]
    out = agent.synthesize(advisory, knowledge, "q")
    assert "Thông tin trường" in out
    assert "24 triệu" in out
    assert "chưa có dữ liệu" in out.lower()


def test_fallback_states_missing_knowledge():
    agent = _agent_with_failing_gateway()
    advisory = AdvisoryBlock(has_data=True, answer="Tư vấn: nên ưu tiên UET.")
    knowledge = [KnowledgeBlock(school="VNU-UET", topic="tuition", has_data=False)]
    out = agent.synthesize(advisory, knowledge, "q")
    assert "nên ưu tiên UET" in out
    assert "chưa có dữ liệu" in out.lower()


def test_merged_sources_are_deduped_and_appended():
    agent = _agent_with_failing_gateway()
    advisory = AdvisoryBlock(has_data=True, answer="A", sources=["https://x", "https://y"])
    knowledge = [
        KnowledgeBlock(school="U", topic="tuition", has_data=True, answer="B", sources=["https://y", "https://z"]),
    ]
    out = agent.synthesize(advisory, knowledge, "q")
    assert "Nguồn:" in out
    # https://y appears once despite being in both blocks
    assert out.count("https://y") == 1
    assert "https://x" in out and "https://z" in out


def test_no_sources_block_when_no_urls():
    agent = _agent_with_failing_gateway()
    advisory = AdvisoryBlock(has_data=True, answer="A")
    knowledge = [KnowledgeBlock(school="U", topic="tuition", has_data=True, answer="B")]
    out = agent.synthesize(advisory, knowledge, "q")
    assert "Nguồn:" not in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/services/chat/test_synthesis_agent.py -v`
Expected: FAIL — `ModuleNotFoundError: services.chat.synthesis_agent`.

- [ ] **Step 3: Create the agent with the deterministic paths**

Create `services/chat/synthesis_agent.py`:

```python
from services import build_default_gateway
from services.chat.hybrid_models import AdvisoryBlock, KnowledgeBlock
from services.inference.models import InferenceRequest

SYNTHESIS_SYSTEM_PROMPT = """
Bạn là trợ lý tổng hợp câu trả lời tư vấn tuyển sinh đại học Việt Nam.
Bạn nhận hai khối thông tin đã được chuẩn bị sẵn:
- Khối A (Dữ liệu tuyển sinh): kết quả phân tích điểm chuẩn / khả năng đậu.
- Khối B (Thông tin trường): các dữ kiện thực tế (học phí, chương trình, học bổng...).

Quy tắc bắt buộc:
- CHỈ sắp xếp, đối chiếu và diễn đạt lại nội dung trong hai khối được cung cấp.
- TUYỆT ĐỐI không thêm bất kỳ số liệu, sự kiện hay nhận định nào không có trong hai khối.
- Nếu một khối thiếu dữ liệu, nói rõ phần đó chưa có dữ liệu, không suy diễn.
- Trình bày thành hai mục rõ ràng: "Theo dữ liệu tuyển sinh" và "Thông tin trường".
- Khi so sánh nhiều trường, ưu tiên lập bảng đối chiếu ngắn gọn.
- Không tự liệt kê nguồn; hệ thống sẽ tự gắn nguồn.
- Trả lời bằng tiếng Việt, định dạng markdown.

Chỉ trả về nội dung câu trả lời cuối cùng cho người dùng, không trả JSON.
""".strip()


class SynthesisAgent:
    def __init__(self, gateway=None):
        self._gateway = gateway or build_default_gateway()

    def synthesize(self, advisory: AdvisoryBlock, knowledge: list, question: str) -> str:
        try:
            body = self._llm_synthesize(advisory, knowledge, question)
        except Exception:
            body = self._concatenate(advisory, knowledge)
        sources = self._merge_sources(advisory, knowledge)
        if sources:
            body = f"{body}\n\nNguồn:\n" + "\n".join(f"- {url}" for url in sources)
        return body

    def _llm_synthesize(self, advisory, knowledge, question) -> str:
        raise NotImplementedError  # implemented in Task 4

    @staticmethod
    def _merge_sources(advisory: AdvisoryBlock, knowledge: list) -> list:
        urls = []
        for url in advisory.sources:
            if url and url not in urls:
                urls.append(url)
        for block in knowledge:
            for url in block.sources:
                if url and url not in urls:
                    urls.append(url)
        return urls

    @staticmethod
    def _concatenate(advisory: AdvisoryBlock, knowledge: list) -> str:
        parts = []
        if advisory.has_data and advisory.answer:
            parts.append(f"**Theo dữ liệu tuyển sinh:**\n{advisory.answer}")
        else:
            parts.append("**Theo dữ liệu tuyển sinh:** Hệ thống chưa có dữ liệu tư vấn cho câu hỏi này.")

        kb_lines = []
        for block in knowledge:
            if block.has_data and block.answer:
                label = block.school or ""
                kb_lines.append(f"- {label}: {block.answer}" if label else f"- {block.answer}")
        if kb_lines:
            parts.append("**Thông tin trường:**\n" + "\n".join(kb_lines))
        else:
            parts.append("**Thông tin trường:** Hệ thống chưa có dữ liệu cho phần này.")

        return "\n\n".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/services/chat/test_synthesis_agent.py -v`
Expected: PASS — `_llm_synthesize` raises `NotImplementedError`, so `synthesize` falls through to `_concatenate` for every test here.

- [ ] **Step 5: Commit**

```bash
git add services/chat/synthesis_agent.py tests/services/chat/test_synthesis_agent.py
git commit -m "feat(hybrid): SynthesisAgent deterministic fallback + merged source list"
```

---

### Task 4: `SynthesisAgent` — grounded LLM synthesis path

**Files:**
- Modify: `services/chat/synthesis_agent.py` (`_llm_synthesize` + a prompt builder)
- Test: `tests/services/chat/test_synthesis_agent.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/services/chat/test_synthesis_agent.py`:

```python
from services.inference.models import InferenceResult


class RecordingGateway:
    def __init__(self, content="**Theo dữ liệu tuyển sinh**\n...\n**Thông tin trường**\n..."):
        self._content = content
        self.last_request = None

    def is_available(self):
        return True

    def run(self, request):
        self.last_request = request
        return InferenceResult(
            agent_name=request.agent_name, model="m", provider="p", content=self._content,
        )


def test_llm_path_used_when_gateway_returns_content():
    gw = RecordingGateway(content="Câu trả lời tổng hợp từ LLM.")
    agent = SynthesisAgent(gateway=gw)
    advisory = AdvisoryBlock(has_data=True, answer="adv", sources=["https://x"])
    knowledge = [KnowledgeBlock(school="U", topic="tuition", has_data=True, answer="kno", sources=["https://y"])]
    out = agent.synthesize(advisory, knowledge, "so sánh U")
    assert "Câu trả lời tổng hợp từ LLM." in out
    assert gw.last_request.agent_name == "synthesis_agent"
    assert gw.last_request.output_mode == "free_text"
    # sources still appended deterministically (not trusted to the LLM)
    assert "https://x" in out and "https://y" in out


def test_prompt_carries_grounding_rule_and_both_blocks():
    gw = RecordingGateway()
    agent = SynthesisAgent(gateway=gw)
    advisory = AdvisoryBlock(has_data=True, answer="ADV_TEXT")
    knowledge = [KnowledgeBlock(school="VNU-UET", topic="tuition", has_data=True, answer="KNO_TEXT")]
    agent.synthesize(advisory, knowledge, "câu hỏi gốc")
    sys = gw.last_request.system_prompt
    usr = gw.last_request.user_prompt
    assert "không thêm" in sys.lower() or "tuyệt đối không" in sys.lower()
    assert "ADV_TEXT" in usr
    assert "KNO_TEXT" in usr
    assert "VNU-UET" in usr
    assert "câu hỏi gốc" in usr


def test_empty_llm_content_falls_back_to_concatenation():
    gw = RecordingGateway(content="   ")  # whitespace only
    agent = SynthesisAgent(gateway=gw)
    advisory = AdvisoryBlock(has_data=True, answer="adv only")
    knowledge = [KnowledgeBlock(school="U", topic="tuition", has_data=False)]
    out = agent.synthesize(advisory, knowledge, "q")
    assert "adv only" in out
    assert "Theo dữ liệu tuyển sinh" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/services/chat/test_synthesis_agent.py -k "llm_path or grounding_rule or empty_llm_content" -v`
Expected: FAIL — `_llm_synthesize` still raises `NotImplementedError`, so the LLM content never appears.

- [ ] **Step 3: Implement `_llm_synthesize` + prompt builder**

In `services/chat/synthesis_agent.py`, replace the `_llm_synthesize` stub with:

```python
    def _llm_synthesize(self, advisory, knowledge, question) -> str:
        if hasattr(self._gateway, "is_available") and not self._gateway.is_available():
            raise RuntimeError("gateway unavailable")
        result = self._gateway.run(
            InferenceRequest(
                agent_name="synthesis_agent",
                task_type="hybrid_synthesis",
                system_prompt=SYNTHESIS_SYSTEM_PROMPT,
                user_prompt=self._build_user_prompt(advisory, knowledge, question),
                output_mode="free_text",
                temperature=0.0,
            )
        )
        text = (result.content or "").strip()
        if not text:
            raise ValueError("empty synthesis content")
        return text

    @staticmethod
    def _build_user_prompt(advisory, knowledge, question) -> str:
        lines = [f"Câu hỏi của người dùng: {question}", ""]
        lines.append("Khối A — Dữ liệu tuyển sinh:")
        if advisory.has_data and advisory.answer:
            lines.append(advisory.answer)
        else:
            lines.append("(chưa có dữ liệu)")
        lines.append("")
        lines.append("Khối B — Thông tin trường:")
        any_kb = False
        for block in knowledge:
            if block.has_data and block.answer:
                any_kb = True
                label = " · ".join(x for x in [block.school, block.topic] if x)
                prefix = f"[{label}] " if label else ""
                lines.append(f"{prefix}{block.answer}")
        if not any_kb:
            lines.append("(chưa có dữ liệu)")
        return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/services/chat/test_synthesis_agent.py -v`
Expected: PASS — both the LLM path and the fallback path covered.

- [ ] **Step 5: Commit**

```bash
git add services/chat/synthesis_agent.py tests/services/chat/test_synthesis_agent.py
git commit -m "feat(hybrid): grounded LLM synthesis path with empty-content fallback"
```

---

## Self-Review

- **Spec coverage:** Decision 6 (LLM synthesis under grounding rule + deterministic fallback) → Tasks 3 & 4. "Merged citations, deduped by URL" → Task 3 `_merge_sources` + test. "Two labelled sections" → asserted in both LLM and fallback tests. Inference registration → Task 2.
- **Placeholder scan:** None — `_llm_synthesize` is a deliberate `NotImplementedError` stub in Task 3 that Task 4 replaces, with passing tests at each step; not a plan placeholder.
- **Type consistency:** `synthesize(advisory: AdvisoryBlock, knowledge: list[KnowledgeBlock], question: str) -> str` is the exact signature Phase 5c's `CompareOrchestrator` calls; `AdvisoryBlock`/`KnowledgeBlock` field names (`has_data`, `answer`, `sources`, `school`, `topic`) match Phase 5c's builders.
