# Phase 5a — Router HYBRID Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the intent router so a `HYBRID` classification carries the multiple schools, multiple topics, and an explicit `needs_advisory` flag the Phase 5 orchestrator needs.

**Architecture:** Add three optional fields to `IntentResult` (`schools`, `topics`, `needs_advisory`) that default to empty/false so every non-HYBRID route is unaffected, and teach `INTENT_SYSTEM_PROMPT` to emit them for HYBRID. No execution logic changes here — this plan only widens the router's output contract.

**Tech Stack:** Python, Pydantic, pytest. LLM gateway via `services/inference`.

**Spec:** [`../specs/2026-05-30-phase-5-hybrid-compare-agent-design.md`](../specs/2026-05-30-phase-5-hybrid-compare-agent-design.md) — decision 2 & 3.

---

### Task 1: Add `schools`, `topics`, `needs_advisory` to `IntentResult`

**Files:**
- Modify: `services/chat/intent_router.py` (the `IntentResult` model, ~lines 42-57)
- Test: `tests/services/chat/test_intent_router.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/services/chat/test_intent_router.py`:

```python
# --- HYBRID schema (Phase 5a) ---

def test_intent_result_hybrid_fields_default_empty():
    result = IntentResult(route="ADVISORY_FLOW")
    assert result.schools == []
    assert result.topics == []
    assert result.needs_advisory is False


def test_intent_result_hybrid_full_payload():
    result = IntentResult.model_validate({
        "route": "HYBRID",
        "schools": ["VNU-UET", "HUST"],
        "topics": ["tuition", "curriculum"],
        "needs_advisory": True,
    })
    assert result.route == "HYBRID"
    assert result.schools == ["VNU-UET", "HUST"]
    assert result.topics == ["tuition", "curriculum"]
    assert result.needs_advisory is True


def test_intent_result_hybrid_rejects_invalid_topic_in_list():
    with pytest.raises(Exception):
        IntentResult.model_validate({"route": "HYBRID", "topics": ["not_a_topic"]})


def test_intent_result_singular_fields_still_work():
    result = IntentResult(route="KNOWLEDGE_QA", topic="tuition", school="NEU")
    assert result.topic == "tuition"
    assert result.school == "NEU"
    assert result.schools == []
    assert result.topics == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/services/chat/test_intent_router.py -k "hybrid or singular_fields_still" -v`
Expected: FAIL — `IntentResult` has no `schools`/`topics`/`needs_advisory` attributes (AttributeError / ValidationError).

- [ ] **Step 3: Add the fields**

In `services/chat/intent_router.py`, replace the `IntentResult` class body with:

```python
class IntentResult(BaseModel):
    route: Literal[
        "ADVISORY_FLOW", "KNOWLEDGE_QA", "HYBRID", "CLARIFICATION", "OUT_OF_SCOPE"
    ]
    topic: Optional[
        Literal[
            "tuition",
            "curriculum",
            "scholarship",
            "dormitory",
            "career",
            "admission_policy",
            "program_overview",
        ]
    ] = None
    school: Optional[str] = None
    # HYBRID-only; default empty/false → no behavior change for other routes.
    schools: List[str] = Field(default_factory=list)
    topics: List[
        Literal[
            "tuition",
            "curriculum",
            "scholarship",
            "dormitory",
            "career",
            "admission_policy",
            "program_overview",
        ]
    ] = Field(default_factory=list)
    needs_advisory: bool = False
```

Update the imports at the top of the file:

```python
from typing import List, Literal, Optional

from pydantic import BaseModel, Field
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/services/chat/test_intent_router.py -v`
Expected: PASS — all new tests plus every existing router test still green.

- [ ] **Step 5: Commit**

```bash
git add services/chat/intent_router.py tests/services/chat/test_intent_router.py
git commit -m "feat(intent): add HYBRID schools/topics/needs_advisory to IntentResult"
```

---

### Task 2: Teach `INTENT_SYSTEM_PROMPT` to emit the HYBRID payload

**Files:**
- Modify: `services/chat/intent_router.py` (the `INTENT_SYSTEM_PROMPT` string, ~lines 9-39)
- Test: `tests/services/chat/test_intent_router.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/services/chat/test_intent_router.py`:

```python
# --- HYBRID classification + prompt wording (Phase 5a) ---

def test_classify_hybrid_compare_scores_and_tuition():
    r = _router(parsed_data={
        "route": "HYBRID",
        "schools": ["VNU-UET", "HUST"],
        "topics": ["tuition"],
        "needs_advisory": True,
    })
    result = r.classify("so sánh UET và HUST về điểm chuẩn lẫn học phí", ChatProfileState())
    assert result.route == "HYBRID"
    assert result.schools == ["VNU-UET", "HUST"]
    assert result.topics == ["tuition"]
    assert result.needs_advisory is True


def test_classify_hybrid_pure_knowledge_comparison_sets_needs_advisory_false():
    r = _router(parsed_data={
        "route": "HYBRID",
        "schools": ["VNU-UET", "HUST"],
        "topics": ["tuition"],
        "needs_advisory": False,
    })
    result = r.classify("so sánh học phí UET và HUST", ChatProfileState())
    assert result.route == "HYBRID"
    assert result.needs_advisory is False


def test_intent_prompt_documents_hybrid_payload():
    from services.chat.intent_router import INTENT_SYSTEM_PROMPT
    assert "needs_advisory" in INTENT_SYSTEM_PROMPT
    assert "schools" in INTENT_SYSTEM_PROMPT
    assert "topics" in INTENT_SYSTEM_PROMPT
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/services/chat/test_intent_router.py -k "hybrid_payload or hybrid_compare or pure_knowledge_comparison" -v`
Expected: FAIL — `test_intent_prompt_documents_hybrid_payload` fails (prompt lacks the new keys); the classify tests already pass because `FakeGateway` returns the dict directly, but keep them — they lock the contract.

- [ ] **Step 3: Extend the system prompt**

In `services/chat/intent_router.py`, replace the trailing lines of `INTENT_SYSTEM_PROMPT` (from `Chuẩn hóa tên trường...` to the end) with:

```python
Chuẩn hóa tên trường thành viết tắt phổ biến nếu nhận ra: VNU-UET, HUST, NEU, VNU-HCMUS, UEH, FTU, ...

Với route HYBRID, trả thêm các trường:
- "schools": danh sách trường cần so sánh, ví dụ ["VNU-UET", "HUST"]
- "topics": danh sách chủ đề knowledge cần tra cứu, ví dụ ["tuition", "curriculum"]
- "needs_advisory": true nếu câu hỏi cần dữ liệu điểm chuẩn / khả năng đậu;
  false nếu chỉ so sánh thông tin thực tế (ví dụ chỉ học phí giữa các trường)

Ví dụ HYBRID:
"So sánh UET và HUST về điểm chuẩn lẫn học phí"
→ {"route":"HYBRID","schools":["VNU-UET","HUST"],"topics":["tuition"],"needs_advisory":true}
"So sánh học phí UET và HUST"
→ {"route":"HYBRID","schools":["VNU-UET","HUST"],"topics":["tuition"],"needs_advisory":false}

Trả về JSON hợp lệ, không giải thích thêm.
Với các route khác (không phải HYBRID) chỉ cần:
{"route": "...", "topic": "...", "school": "..."}
""".strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/services/chat/test_intent_router.py -v`
Expected: PASS — full router suite green.

- [ ] **Step 5: Commit**

```bash
git add services/chat/intent_router.py tests/services/chat/test_intent_router.py
git commit -m "feat(intent): prompt the router to emit the HYBRID schools/topics/needs_advisory payload"
```

---

## Self-Review

- **Spec coverage:** Decision 2 (new fields, backward compatible) → Task 1. Decision 3 (`needs_advisory=false` for pure-knowledge comparisons) → Task 2 prompt + test. Acceptance "compare question → HYBRID with both branches" partially served (router side) by Task 2.
- **Placeholder scan:** None — every step has concrete code/commands.
- **Type consistency:** `schools: List[str]`, `topics: List[Literal[...]]`, `needs_advisory: bool` match how Tasks 5c/5d consume `intent.schools` / `intent.topics` / `intent.needs_advisory`.
