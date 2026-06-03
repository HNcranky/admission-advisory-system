# Phase 1 — Plan 2: IntentRouter Service

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `IntentRouter` — a self-contained service that classifies a user message into one of 5 routes (`ADVISORY_FLOW`, `KNOWLEDGE_QA`, `HYBRID`, `CLARIFICATION`, `OUT_OF_SCOPE`) via a single LLM call, with a guaranteed `ADVISORY_FLOW` fallback on any failure.

**Architecture:** `IntentResult` and `IntentRouter` live in `services/chat/intent_router.py`. `IntentRouter` follows the exact gateway-injection pattern of `build_profile_with_gateway` in `services/profile_inference_service.py`: the gateway is injected in the constructor, it short-circuits to fallback when `gateway.is_available()` is false, and `classify()` wraps everything in one `try/except Exception` so it never raises. `IntentResult` has **no** `return_to_flow` field — "is the user mid-flow?" is computed deterministically in `ConversationService` from `FlowState`, never guessed by the LLM.

**Tech Stack:** Python 3.11, Pydantic v2, `InferenceRequest` / `InferenceResult` / `InferenceError` from `services.inference.models`, `build_default_gateway` from `services`, pytest

**Depends on:** Plan 1 complete (`FlowState` + `ChatProfileState` available in `services/chat/models.py`).

**Spec:** `docs/superpowers/specs/2026-05-30-phase1-intent-router-flow-state-design.md` (§1 IntentRouter Service)

---

### Task 1: IntentResult Model + IntentRouter skeleton

**Files:**
- Create: `services/chat/intent_router.py`
- Test: `tests/services/chat/test_intent_router.py`

- [ ] **Step 1: Create test file with failing tests**

Create `tests/services/chat/test_intent_router.py`:

```python
import pytest

from services.chat.intent_router import IntentResult


def test_intent_result_defaults():
    result = IntentResult(route="ADVISORY_FLOW")
    assert result.route == "ADVISORY_FLOW"
    assert result.topic is None
    assert result.school is None


def test_intent_result_full():
    result = IntentResult(route="KNOWLEDGE_QA", topic="tuition", school="VNU-UET")
    assert result.route == "KNOWLEDGE_QA"
    assert result.topic == "tuition"
    assert result.school == "VNU-UET"


def test_intent_result_has_no_return_to_flow_field():
    """return_to_flow was removed; it must not be a model field."""
    assert "return_to_flow" not in IntentResult.model_fields


def test_intent_result_rejects_invalid_route():
    with pytest.raises(Exception):
        IntentResult(route="INVALID_ROUTE")


def test_intent_result_rejects_invalid_topic():
    with pytest.raises(Exception):
        IntentResult(route="KNOWLEDGE_QA", topic="invalid_topic")


def test_intent_result_model_validate_from_dict():
    result = IntentResult.model_validate({"route": "OUT_OF_SCOPE"})
    assert result.route == "OUT_OF_SCOPE"
    assert result.topic is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/services/chat/test_intent_router.py -v`
Expected: `ModuleNotFoundError: No module named 'services.chat.intent_router'`

- [ ] **Step 3: Create intent_router.py**

Create `services/chat/intent_router.py`:

```python
from typing import Literal, Optional

from pydantic import BaseModel

from services import build_default_gateway
from services.chat.models import ChatProfileState
from services.inference.models import InferenceRequest

INTENT_SYSTEM_PROMPT = """
Bạn là bộ phân loại intent cho hệ thống tư vấn tuyển sinh đại học Việt Nam.

Phân loại tin nhắn của user vào đúng 1 trong 5 route:

ADVISORY_FLOW — câu hỏi tư vấn chọn ngành/trường dựa trên điểm số, nguyện vọng, khả năng đậu
  Ví dụ: "25 điểm A00 nên chọn trường nào", "em có đậu NEU không", "tư vấn ngành CNTT"

KNOWLEDGE_QA — câu hỏi thực tế về thông tin cụ thể của trường/ngành
  Ví dụ: "học phí UET bao nhiêu", "chương trình CNTT gồm gì", "có học bổng không", "ký túc xá thế nào"

CLARIFICATION — câu quá mơ hồ, thiếu context để phân loại chính xác
  Ví dụ: "thế còn cái đó thì sao" (không rõ đối tượng), "ý bạn là gì"

OUT_OF_SCOPE — hoàn toàn ngoài lĩnh vực tuyển sinh đại học
  Ví dụ: "thời tiết hôm nay", "kể chuyện cười", "1+1 bằng mấy", "giúp tôi viết code"

HYBRID — cần cả dữ liệu tư vấn (điểm chuẩn, xác suất đậu) lẫn thông tin thực tế (học phí, chương trình)
  Ví dụ: "so sánh UET và HUST về điểm chuẩn lẫn học phí"
  Chỉ dùng HYBRID khi câu hỏi thực sự cần cả hai loại dữ liệu.

Quy tắc resolve đại từ:
- "trường này", "ở đó", "trường đó" → dùng preferred_schools trong profile (nếu có)
- "ngành này", "chuyên ngành đó" → dùng preferred_majors trong profile (nếu có)
- Không thể resolve → để school/topic là null, route về CLARIFICATION

Chuẩn hóa tên trường thành viết tắt phổ biến nếu nhận ra: VNU-UET, HUST, NEU, VNU-HCMUS, UEH, FTU, ...

Trả về JSON hợp lệ, không giải thích thêm:
{"route": "...", "topic": "...", "school": "..."}
""".strip()


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


_FALLBACK = IntentResult(route="ADVISORY_FLOW")


class IntentRouter:
    def __init__(self, gateway=None):
        self._gateway = gateway or build_default_gateway()

    def classify(self, message: str, profile_state: ChatProfileState) -> IntentResult:
        try:
            if hasattr(self._gateway, "is_available") and not self._gateway.is_available():
                return _FALLBACK
            result = self._gateway.run(
                InferenceRequest(
                    agent_name="intent_router",
                    task_type="intent_classification",
                    system_prompt=INTENT_SYSTEM_PROMPT,
                    user_prompt=self._build_user_prompt(message, profile_state),
                    output_mode="json",
                    temperature=0.0,
                )
            )
            if not result.parsed_data:
                return _FALLBACK
            return IntentResult.model_validate(result.parsed_data)
        except Exception:
            return _FALLBACK

    def _build_user_prompt(self, message: str, profile_state: ChatProfileState) -> str:
        schools = (
            ", ".join(profile_state.preferred_schools)
            if profile_state.preferred_schools
            else "chưa có"
        )
        majors = (
            ", ".join(profile_state.preferred_majors)
            if profile_state.preferred_majors
            else "chưa có"
        )
        return (
            f'Tin nhắn: "{message}"\n\n'
            f"Profile hiện tại:\n"
            f"- Trường quan tâm: {schools}\n"
            f"- Ngành quan tâm: {majors}\n"
            f"- Điểm số: {profile_state.total_score or 'chưa có'}\n"
            f"- Khối thi: {profile_state.subject_combination or 'chưa có'}"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/services/chat/test_intent_router.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add services/chat/intent_router.py tests/services/chat/test_intent_router.py
git commit -m "feat: add IntentResult model and IntentRouter skeleton"
```

---

### Task 2: User prompt builder tests

**Files:**
- Modify: `tests/services/chat/test_intent_router.py` (extend)
- No change to `services/chat/intent_router.py` — `_build_user_prompt` is already implemented in Task 1.

- [ ] **Step 1: Add failing-then-passing tests for _build_user_prompt**

Append to `tests/services/chat/test_intent_router.py`:

```python
from services.chat.models import ChatProfileState
from services.chat.intent_router import IntentRouter


def _prompt_router():
    """Router whose gateway is a dummy object — _build_user_prompt never touches it."""
    return IntentRouter(gateway=object())


def test_build_user_prompt_includes_message():
    prompt = _prompt_router()._build_user_prompt("học phí UET bao nhiêu", ChatProfileState())
    assert "học phí UET bao nhiêu" in prompt


def test_build_user_prompt_includes_preferred_schools():
    profile = ChatProfileState(preferred_schools=["VNU-UET", "HUST"])
    prompt = _prompt_router()._build_user_prompt("msg", profile)
    assert "VNU-UET" in prompt
    assert "HUST" in prompt


def test_build_user_prompt_shows_chua_co_when_empty():
    prompt = _prompt_router()._build_user_prompt("msg", ChatProfileState())
    assert "chưa có" in prompt


def test_build_user_prompt_includes_score_and_combination():
    profile = ChatProfileState(total_score=25.0, subject_combination="A00")
    prompt = _prompt_router()._build_user_prompt("msg", profile)
    assert "25.0" in prompt
    assert "A00" in prompt


def test_build_user_prompt_has_no_return_to_flow_line():
    """return_to_flow was removed from the prompt — the LLM must not be asked to compute it."""
    prompt = _prompt_router()._build_user_prompt("msg", ChatProfileState(total_score=25.0))
    assert "return_to_flow" not in prompt
```

- [ ] **Step 2: Run the prompt-builder tests**

Run: `pytest tests/services/chat/test_intent_router.py -k "prompt" -v`
Expected: 5 passed

- [ ] **Step 3: Commit**

```bash
git add tests/services/chat/test_intent_router.py
git commit -m "test: add user prompt builder tests for IntentRouter"
```

---

### Task 3: classify() — FakeGateway + 21 route/failure cases

**Files:**
- Modify: `tests/services/chat/test_intent_router.py` (extend)
- No change to `services/chat/intent_router.py`.

This satisfies the spec's "≥ 20 cases covering 5 routes" requirement (5 advisory + 5 knowledge + 4 out-of-scope + 3 clarification + 4 failure/degraded = 21).

- [ ] **Step 1: Add FakeGateway helper and all classify tests**

Append to `tests/services/chat/test_intent_router.py`:

```python
from services.inference.models import InferenceError, InferenceResult


class FakeGateway:
    def __init__(self, parsed_data=None, should_raise=False, available=True):
        self._parsed_data = parsed_data
        self._should_raise = should_raise
        self._available = available

    def is_available(self):
        return self._available

    def run(self, request):
        if self._should_raise:
            raise InferenceError("simulated failure")
        return InferenceResult(
            agent_name=request.agent_name,
            model="test-model",
            provider="test",
            content="{}",
            parsed_data=self._parsed_data,
        )


def _router(**kwargs):
    return IntentRouter(gateway=FakeGateway(**kwargs))


# --- ADVISORY_FLOW (5) ---

def test_classify_advisory_basic():
    r = _router(parsed_data={"route": "ADVISORY_FLOW"})
    assert r.classify("25 điểm A00 nên chọn trường nào", ChatProfileState()).route == "ADVISORY_FLOW"


def test_classify_advisory_eligibility():
    r = _router(parsed_data={"route": "ADVISORY_FLOW"})
    assert r.classify("em có đậu NEU không", ChatProfileState()).route == "ADVISORY_FLOW"


def test_classify_advisory_major_advice():
    r = _router(parsed_data={"route": "ADVISORY_FLOW"})
    assert r.classify("tư vấn ngành CNTT cho mình", ChatProfileState()).route == "ADVISORY_FLOW"


def test_classify_advisory_score_combination():
    r = _router(parsed_data={"route": "ADVISORY_FLOW"})
    assert r.classify("điểm 28 khối B00 nên nộp đâu", ChatProfileState()).route == "ADVISORY_FLOW"


def test_classify_advisory_chance_question():
    r = _router(parsed_data={"route": "ADVISORY_FLOW"})
    assert r.classify("cơ hội đậu Bách Khoa của em là bao nhiêu", ChatProfileState()).route == "ADVISORY_FLOW"


# --- KNOWLEDGE_QA (5) ---

def test_classify_knowledge_tuition_with_school():
    r = _router(parsed_data={"route": "KNOWLEDGE_QA", "topic": "tuition", "school": "VNU-UET"})
    result = r.classify("học phí UET bao nhiêu", ChatProfileState())
    assert result.route == "KNOWLEDGE_QA"
    assert result.topic == "tuition"
    assert result.school == "VNU-UET"


def test_classify_knowledge_curriculum():
    r = _router(parsed_data={"route": "KNOWLEDGE_QA", "topic": "curriculum", "school": None})
    result = r.classify("chương trình CNTT gồm gì", ChatProfileState())
    assert result.route == "KNOWLEDGE_QA"
    assert result.topic == "curriculum"


def test_classify_knowledge_scholarship():
    r = _router(parsed_data={"route": "KNOWLEDGE_QA", "topic": "scholarship"})
    result = r.classify("có học bổng không", ChatProfileState())
    assert result.route == "KNOWLEDGE_QA"
    assert result.topic == "scholarship"


def test_classify_knowledge_dormitory():
    r = _router(parsed_data={"route": "KNOWLEDGE_QA", "topic": "dormitory"})
    result = r.classify("ký túc xá thế nào", ChatProfileState())
    assert result.route == "KNOWLEDGE_QA"
    assert result.topic == "dormitory"


def test_classify_knowledge_pronoun_resolved_from_profile():
    """'trường này' resolved to preferred_schools by the LLM; router passes it through."""
    r = _router(parsed_data={"route": "KNOWLEDGE_QA", "topic": "tuition", "school": "VNU-UET"})
    profile = ChatProfileState(preferred_schools=["VNU-UET"])
    result = r.classify("trường này học phí bao nhiêu", profile)
    assert result.route == "KNOWLEDGE_QA"
    assert result.school == "VNU-UET"


# --- OUT_OF_SCOPE (4) ---

def test_classify_out_of_scope_weather():
    r = _router(parsed_data={"route": "OUT_OF_SCOPE"})
    assert r.classify("thời tiết hôm nay thế nào", ChatProfileState()).route == "OUT_OF_SCOPE"


def test_classify_out_of_scope_joke():
    r = _router(parsed_data={"route": "OUT_OF_SCOPE"})
    assert r.classify("kể cho tôi nghe một câu chuyện cười", ChatProfileState()).route == "OUT_OF_SCOPE"


def test_classify_out_of_scope_coding_help():
    r = _router(parsed_data={"route": "OUT_OF_SCOPE"})
    assert r.classify("giúp tôi viết code Python", ChatProfileState()).route == "OUT_OF_SCOPE"


def test_classify_out_of_scope_food():
    r = _router(parsed_data={"route": "OUT_OF_SCOPE"})
    assert r.classify("hôm nay ăn gì ngon", ChatProfileState()).route == "OUT_OF_SCOPE"


# --- CLARIFICATION (3) ---

def test_classify_clarification_ambiguous_pronoun():
    r = _router(parsed_data={"route": "CLARIFICATION"})
    assert r.classify("thế còn cái đó thì sao", ChatProfileState()).route == "CLARIFICATION"


def test_classify_clarification_vague():
    r = _router(parsed_data={"route": "CLARIFICATION"})
    assert r.classify("ý bạn là gì", ChatProfileState()).route == "CLARIFICATION"


def test_classify_clarification_no_context():
    r = _router(parsed_data={"route": "CLARIFICATION"})
    assert r.classify("còn nữa không", ChatProfileState()).route == "CLARIFICATION"


# --- FALLBACK / DEGRADED (4) ---

def test_classify_fallback_on_inference_error():
    result = _router(should_raise=True).classify("bất kỳ câu gì", ChatProfileState())
    assert result.route == "ADVISORY_FLOW"
    assert result.topic is None
    assert result.school is None


def test_classify_fallback_when_parsed_data_is_none():
    result = _router(parsed_data=None).classify("bất kỳ câu gì", ChatProfileState())
    assert result.route == "ADVISORY_FLOW"


def test_classify_fallback_on_invalid_route_in_response():
    """LLM returns a route outside the Literal → validation error → fallback."""
    result = _router(parsed_data={"route": "MADE_UP_ROUTE"}).classify("x", ChatProfileState())
    assert result.route == "ADVISORY_FLOW"


def test_classify_fallback_when_gateway_unavailable():
    """is_available() false → skip the LLM call entirely, return fallback."""
    result = _router(available=False, parsed_data={"route": "OUT_OF_SCOPE"}).classify("x", ChatProfileState())
    assert result.route == "ADVISORY_FLOW"
```

- [ ] **Step 2: Run all IntentRouter tests**

Run: `pytest tests/services/chat/test_intent_router.py -v`
Expected: 32 passed (6 model + 5 prompt + 21 classify)

- [ ] **Step 3: Run the full suite for regressions**

Run: `pytest --tb=short -q`
Expected: all existing tests still pass

- [ ] **Step 4: Commit**

```bash
git add tests/services/chat/test_intent_router.py
git commit -m "test: add 21 classify cases for IntentRouter (5 routes + failure/degraded)"
```

---

## Plan 2 done — exit criteria

- `IntentResult` has exactly `route`, `topic`, `school` — no `return_to_flow`.
- `IntentRouter.classify` never raises: returns `ADVISORY_FLOW` on gateway-unavailable, inference error, empty `parsed_data`, or schema-invalid response.
- The user prompt contains no `return_to_flow` instruction.
- 32 tests pass; no regressions.

**Next:** Plan 3 (ConversationService routing) depends on `IntentRouter` + `IntentResult`.
