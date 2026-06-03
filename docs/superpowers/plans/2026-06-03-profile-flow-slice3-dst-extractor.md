# Slice 3 — DST Extractor + Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mỗi lượt chỉ **một** lần trích xuất hồ sơ (bỏ double-extract), trích xuất **có state** (state-update) thay vì stateless, và merge **correction-aware** bằng delta.

**Architecture:** `extract_profile_update()` (module `services/profile/extractor.py`) trả về **delta** (chỉ slot thay đổi): Tier-0 deterministic cho slot đang chờ → ủy thác `preferred_majors` cho `resolve_majors` (Slice 2) → một LLM call structured-output state-update cho các slot còn lại; skip LLM khi câu trả lời cụt đã điền slot. `apply_profile_delta()` áp delta lên `ChatProfileState` (`{**current, **delta}`) cho phép đính chính. `ConversationService` gọi extractor **đúng một lần/lượt** rồi luồng cả nhánh continue lẫn advisory dùng chung delta.

**Tech Stack:** Python 3, Pydantic v2, pytest. Phụ thuộc Slice 1 (registry) + Slice 2 (resolver) đã merge.

**Spec:** `docs/superpowers/specs/2026-06-03-profile-flow-dst-redesign-design.md` §7.

> **Quy ước repo (CLAUDE.md):** KHÔNG `git push`; không attribution AI. LLM call degrade gracefully + `logger.warning`.

---

## File Structure

- **Create** `services/profile/extractor.py` — `extract_profile_update()`, `apply_profile_delta()`, helpers.
- **Create** `tests/services/profile/test_extractor.py` — unit (fakes).
- **Create** `tests/services/profile/test_apply_delta.py` — unit.
- **Modify** `services/chat/conversation_service.py` — extract 1 lần/lượt; dùng delta + `apply_profile_delta`.
- **Modify** `tests/services/chat/test_conversation_service.py` — chuyển fake `extract` từ `StudentProfile` sang **delta dict**; thêm regression đếm số lần extract.

---

## Task 1: `extract_profile_update()` — DST delta extractor

**Files:**
- Create: `services/profile/extractor.py`
- Test: `tests/services/profile/test_extractor.py`

- [ ] **Step 1: Viết test thất bại (deterministic, resolver, skip-LLM, degrade)**

Create `tests/services/profile/test_extractor.py`:

```python
from types import SimpleNamespace

from services.inference.models import InferenceError, InferenceResult
from services.profile.extractor import extract_profile_update


def _state(**kw):
    base = dict(admission_year=None, total_score=None, subject_combination=None,
                preferred_majors=[], preferred_schools=[], location_preference=None,
                tuition_budget=None, constraints=[])
    base.update(kw)
    return SimpleNamespace(**base)


class UnavailableGateway:
    def is_available(self):
        return False

    def run(self, request):
        raise AssertionError("không được gọi LLM khi gateway unavailable / bare answer")


class FakeGatewayFields:
    def __init__(self, data):
        self._data = data
        self.calls = 0

    def is_available(self):
        return True

    def run(self, request):
        self.calls += 1
        return InferenceResult(agent_name=request.agent_name, model="f", provider="f",
                               content="{}", parsed_data=self._data)


class FailingGateway:
    def is_available(self):
        return True

    def run(self, request):
        raise InferenceError("llm down")


def _no_majors(text, **kw):
    return []


def test_deterministic_active_slot_bare_answer_skips_llm():
    delta = extract_profile_update(
        "29", known_state=_state(admission_year=2026), active_slot="total_score",
        gateway=UnavailableGateway(), resolver=_no_majors)
    assert delta == {"total_score": 29.0}


def test_resolver_supplies_preferred_majors():
    delta = extract_profile_update(
        "em thích làm app", known_state=_state(), active_slot="preferred_majors",
        gateway=UnavailableGateway(), resolver=lambda text, **kw: ["software_engineering"])
    assert delta["preferred_majors"] == ["software_engineering"]


def test_llm_fills_other_slots_as_delta():
    gw = FakeGatewayFields({"location_preference": "Ha Noi", "subject_combination": "A00"})
    delta = extract_profile_update(
        "mình muốn học ở Hà Nội khối A00", known_state=_state(), active_slot=None,
        gateway=gw, resolver=_no_majors)
    assert delta["location_preference"] == "Ha Noi"
    assert delta["subject_combination"] == "A00"
    assert gw.calls == 1


def test_llm_failure_degrades_to_deterministic_delta():
    delta = extract_profile_update(
        "năm 2026", known_state=_state(), active_slot="admission_year",
        gateway=FailingGateway(), resolver=_no_majors)
    assert delta == {"admission_year": 2026}  # Tier-0 vẫn có, LLM lỗi bị nuốt


def test_llm_output_strips_majors_and_unknown_keys():
    gw = FakeGatewayFields({"preferred_majors": ["xxx"], "garbage": 1, "total_score": 30.0})
    delta = extract_profile_update(
        "mình được 30 điểm", known_state=_state(), active_slot=None,
        gateway=gw, resolver=_no_majors)
    assert delta == {"total_score": 30.0}  # preferred_majors (do resolver lo) & key lạ bị loại
```

- [ ] **Step 2: Chạy để xác nhận FAIL**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/profile/test_extractor.py -v`
Expected: FAIL — `ModuleNotFoundError: services.profile.extractor`.

- [ ] **Step 3: Viết `services/profile/extractor.py`**

Create `services/profile/extractor.py`:

```python
import logging
from typing import Optional

from services.chat.models import ChatProfileState
from services.inference.models import InferenceError, InferenceRequest
from services.profile.major_resolver import resolve_majors
from services.profile.slots import SLOTS, missing_critical_slots, parse_slot

logger = logging.getLogger(__name__)

# Slot vô hướng LLM được phép trả (preferred_majors do resolver; preferred_schools/
# constraints trích cơ hội nhưng vẫn nằm trong allow-list bên dưới nếu LLM trả).
_LLM_SLOT_KEYS = {
    "admission_year", "total_score", "subject_combination",
    "location_preference", "tuition_budget", "preferred_schools", "constraints",
}

STATE_UPDATE_PROMPT = """
Bạn cập nhật hồ sơ tư vấn tuyển sinh của một học sinh Việt Nam qua hội thoại.
Bạn được cho HỒ SƠ ĐÃ BIẾT và TIN NHẮN MỚI. CHỈ trả về các trường THAY ĐỔI
hoặc MỚI xuất hiện trong tin nhắn mới (delta), KHÔNG lặp lại trường không đổi.

Trả JSON, chỉ gồm các khóa có giá trị mới (dùng đúng tên khóa):
- total_score: số (0..40)
- subject_combination: mã tổ hợp "A00"/"A01"/"D01"...
- admission_year: năm (số)
- location_preference: tỉnh/khu vực
- tuition_budget: chuỗi ngân sách
- preferred_schools: list tên trường
- constraints: list ràng buộc
KHÔNG trả preferred_majors (hệ thống tự suy). Nếu tin nhắn không thêm gì, trả {}.
""".strip()


def _is_bare_answer(message: str) -> bool:
    """Câu trả lời cụt: ngắn (<= 4 token) — đủ để coi là chỉ trả lời slot đang hỏi."""
    return len((message or "").split()) <= 4


def _render_state_update(known_state, message: str) -> str:
    known = []
    for s in sorted(SLOTS, key=lambda s: s.order):
        val = getattr(known_state, s.name, None)
        known.append(f"- {s.name}: {val if val not in (None, [], '') else 'chưa có'}")
    missing = ", ".join(missing_critical_slots(known_state)) or "(đủ)"
    return (
        "HỒ SƠ ĐÃ BIẾT:\n" + "\n".join(known) +
        f"\nSlot còn thiếu: {missing}\n\nTIN NHẮN MỚI: \"{message}\""
    )


def _coerce_llm_delta(parsed) -> dict:
    data = dict(parsed or {})
    out = {}
    for key, value in data.items():
        if key not in _LLM_SLOT_KEYS:
            continue
        if value is None or value == [] or value == "":
            continue
        out[key] = value
    return out


def extract_profile_update(message: str, *, known_state, active_slot: Optional[str] = None,
                           gateway=None, resolver=resolve_majors) -> dict:
    """Trả DELTA: chỉ slot thay đổi lượt này (DST update)."""
    message = message or ""
    delta: dict = {}

    # Tier-0: parse câu trả lời cụt cho slot đang chờ (deterministic).
    if active_slot:
        val = parse_slot(active_slot, message)
        if val is not None:
            delta[active_slot] = val

    # preferred_majors: ủy thác resolver tiered (Slice 2). Không bao giờ raise lên.
    try:
        majors = resolver(message, known_state=known_state, gateway=gateway)
    except Exception as exc:
        logger.warning("resolve_majors failed in extractor: %r", exc)
        majors = []
    if majors:
        delta["preferred_majors"] = majors

    # Bare answer đã điền slot đang chờ → khỏi gọi LLM (minimize_num_calls).
    if active_slot and active_slot in delta and _is_bare_answer(message):
        return delta

    if gateway is None:
        from services import build_default_gateway
        gateway = build_default_gateway()
    if hasattr(gateway, "is_available") and not gateway.is_available():
        return delta

    # Một LLM call structured-output, state-update.
    try:
        result = gateway.run(InferenceRequest(
            agent_name="profile_extractor",
            task_type="profile_extraction",
            system_prompt=STATE_UPDATE_PROMPT,
            user_prompt=_render_state_update(known_state, message),
            output_mode="json",
            temperature=0.0,
        ))
        delta.update(_coerce_llm_delta(result.parsed_data))
    except InferenceError as exc:
        logger.warning("profile extractor LLM failed, dùng delta deterministic: %r", exc)

    return delta


def apply_profile_delta(current: ChatProfileState, delta: dict) -> ChatProfileState:
    """Áp delta (override slot có trong delta), recompute missing_slots."""
    merged = current.model_copy(update=delta)
    merged.missing_slots = missing_critical_slots(merged)
    return merged
```

- [ ] **Step 4: Chạy lại test**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/profile/test_extractor.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add services/profile/extractor.py tests/services/profile/test_extractor.py
git commit -m "feat(profile): DST delta extractor with state-update + deterministic-first (slice 3)"
```

---

## Task 2: `apply_profile_delta()` — correction-aware merge

**Files:**
- Test: `tests/services/profile/test_apply_delta.py` (hàm đã viết ở Task 1)

- [ ] **Step 1: Viết test cho merge correction-aware**

Create `tests/services/profile/test_apply_delta.py`:

```python
from services.chat.models import ChatProfileState
from services.profile.extractor import apply_profile_delta


def test_delta_overrides_existing_value_correction():
    current = ChatProfileState(preferred_schools=["hust"])
    merged = apply_profile_delta(current, {"preferred_schools": ["neu"]})
    assert merged.preferred_schools == ["neu"]  # đính chính được


def test_unmentioned_slots_preserved():
    current = ChatProfileState(total_score=25.0, subject_combination="A00")
    merged = apply_profile_delta(current, {"location_preference": "Ha Noi"})
    assert merged.total_score == 25.0
    assert merged.subject_combination == "A00"
    assert merged.location_preference == "Ha Noi"


def test_missing_slots_recomputed_after_apply():
    current = ChatProfileState(admission_year=2026)
    merged = apply_profile_delta(current, {"total_score": 27.0})
    assert "total_score" not in merged.missing_slots
    assert "preferred_majors" in merged.missing_slots
```

- [ ] **Step 2: Chạy để xác nhận PASS**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/profile/test_apply_delta.py -v`
Expected: PASS (3 passed).

- [ ] **Step 3: Commit**

```bash
git add tests/services/profile/test_apply_delta.py
git commit -m "test(profile): correction-aware apply_profile_delta (slice 3)"
```

---

## Task 3: Wire vào `ConversationService` — extract 1 lần/lượt + delta

**Files:**
- Modify: `services/chat/conversation_service.py`
- Test: `tests/services/chat/test_conversation_service.py`

> Đây là task đổi hành vi lớn nhất. Hợp đồng `extract_profile` đổi thành
> `extract_profile(text, known_state, active_slot) -> dict (delta)`. Merge dùng
> `apply_profile_delta` thay `merge_profile_state`. Bare-answer/admission_year được
> parse ở tầng orchestration như lưới an toàn (độc lập với extractor được inject).

- [ ] **Step 1: Viết regression test — extract gọi đúng 1 lần/lượt**

Append vào `tests/services/chat/test_conversation_service.py` (cuối file):

```python
# ─── Slice 3: single extraction per turn (G2) ────────────────────────────────

class CountingExtract:
    def __init__(self, delta=None):
        self.calls = 0
        self._delta = delta or {}

    def __call__(self, text, known_state=None, active_slot=None):
        self.calls += 1
        return dict(self._delta)


def test_extract_called_exactly_once_per_advisory_turn():
    counter = CountingExtract(delta={})
    flow = FlowState(active_flow="ADVISORY_FLOW", pending_question="Bạn đang xét tuyển cho năm nào?")
    service, _ = _make_service(
        intent_result=IntentResult(route="ADVISORY_FLOW"),
        profile=ChatProfileState(),
        flow=flow,
        extract=counter,
    )
    service.handle_user_message("tok", "một câu không điền slot nào")
    assert counter.calls == 1  # KHÔNG double-extract (continue + handle)
```

- [ ] **Step 2: Chạy để xác nhận FAIL**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_conversation_service.py::test_extract_called_exactly_once_per_advisory_turn -v`
Expected: FAIL — code hiện gọi `extract_profile(text)` (1 arg) ở 2 chỗ; `counter` mới ký 3 tham số → `TypeError`/double-call.

- [ ] **Step 3: Sửa imports + `_extract_profile` + 3 method trong `conversation_service.py`**

Thay phần import slot/merge cũ:

```python
from services.chat.profile_state_service import (
    merge_profile_state,
    missing_critical_slots,
    next_follow_up_question,
    parse_pending_slot_answer,
)
```

bằng:

```python
from services.profile.slots import missing_critical_slots, next_follow_up_question, parse_slot
from services.profile.extractor import apply_profile_delta, extract_profile_update
```

Thay default extractor:

```python
    def _extract_profile(self, text: str):
        gateway = build_default_gateway()
        return build_profile_with_gateway(text, gateway)
```

bằng:

```python
    def _extract_profile(self, text: str, known_state=None, active_slot=None):
        gateway = build_default_gateway()
        return extract_profile_update(text, known_state=known_state,
                                      active_slot=active_slot, gateway=gateway)
```

(Có thể bỏ import `build_profile_with_gateway` nếu không còn dùng nơi khác trong file.)

Thay `handle_user_message` (phần đầu tới nhánh route) bằng:

```python
    def handle_user_message(self, session_token: str, content: str) -> ConversationTurnResult:
        self.repository.append_message(session_token, "user", content, "user_message")
        session = self.repository.get_session_by_token(session_token)
        profile_state = self.repository.get_profile_state(session_token)
        flow_state = self.repository.get_flow_state(session_token)

        # Trích xuất ĐÚNG MỘT LẦN/lượt; cả nhánh continue lẫn advisory dùng chung delta.
        active_slot = (missing_critical_slots(profile_state) or [None])[0]
        delta = self.extract_profile(content, profile_state, active_slot)
        delta = self._deterministic_safety_net(delta, content, active_slot)

        continued = self._maybe_continue_advisory(session_token, content, profile_state, flow_state, delta)
        if continued is not None:
            return continued

        intent = self.intent_router.classify(content, profile_state)
        session_status = session.status if session else "collecting_profile"

        if intent.route == "ADVISORY_FLOW":
            return self._handle_advisory(session_token, profile_state, flow_state, delta)
        if intent.route == "KNOWLEDGE_QA":
            return self._handle_knowledge_qa(session_token, content, intent, profile_state, flow_state, session_status)
        if intent.route == "HYBRID":
            return self._handle_hybrid(session_token, content, intent, profile_state, flow_state, session_status)
        if intent.route == "OUT_OF_SCOPE":
            return self._handle_out_of_scope(session_token, profile_state, flow_state, session_status)
        if intent.route == "CONVERSATIONAL":
            return self._handle_conversational(
                session_token, content, intent, profile_state, flow_state, session_status
            )
        return self._handle_clarification(
            session_token, intent, profile_state, flow_state, session_status
        )

    @staticmethod
    def _deterministic_safety_net(delta: dict, content: str, active_slot) -> dict:
        """Parse năm (luôn) và slot đang chờ (nếu có parser) độc lập với extractor.

        Giữ hành vi cũ: admission_year luôn được nhận từ raw; câu trả lời cụt
        cho slot đang chờ (vd "29" -> total_score) vẫn được điền."""
        delta = dict(delta)
        if "admission_year" not in delta:
            year = parse_slot("admission_year", content)
            if year is not None:
                delta["admission_year"] = year
        if active_slot and active_slot != "admission_year" and active_slot not in delta:
            val = parse_slot(active_slot, content)
            if val is not None:
                delta[active_slot] = val
        return delta
```

Thay `_maybe_continue_advisory`:

```python
    def _maybe_continue_advisory(self, session_token, content, profile_state, flow_state, delta):
        if flow_state.active_flow != "ADVISORY_FLOW" or not flow_state.pending_question:
            return None
        pending = missing_critical_slots(profile_state)
        if not pending:
            return None
        pending_slot = pending[0]

        merged = apply_profile_delta(profile_state, delta)
        answered = bool(getattr(merged, pending_slot)) and (
            getattr(merged, pending_slot) != getattr(profile_state, pending_slot)
        )
        if not answered:
            return None
        return self._advance_advisory(session_token, merged, flow_state)
```

Thay `_handle_advisory`:

```python
    def _handle_advisory(self, session_token, profile_state, flow_state, delta):
        merged = apply_profile_delta(profile_state, delta)
        return self._advance_advisory(session_token, merged, flow_state)
```

> `_advance_advisory`, các `_handle_*` khác, `_maybe_offer_resume` GIỮ NGUYÊN.

- [ ] **Step 4: Cập nhật `_make_service` default + các fake `extract` sang delta**

Trong `tests/services/chat/test_conversation_service.py`:

Sửa default trong `_make_service`:

```python
    service = ConversationService(
        repository=repo,
        extract_profile=extract or (lambda text, known_state=None, active_slot=None: {}),
        intent_router=router,
        knowledge_qa=knowledge_qa or FakeKnowledgeQA(),
    )
```

Sửa 2 chỗ tạo `ConversationService` trực tiếp (`test_handle_user_message_returns_follow_up_when_score_missing`, `test_conversation_service_accepts_intent_router_injection`): đổi `extract_profile=lambda text: StudentProfile(...)` → trả **delta dict** với chữ ký `lambda text, known_state=None, active_slot=None:`.

Quy tắc chuyển từng fake `extract=`:
`StudentProfile(preferred_majors=["computer_science"], location_preference="Ha Noi")`
→ `lambda text, known_state=None, active_slot=None: {"preferred_majors": ["computer_science"], "location_preference": "Ha Noi"}`
`StudentProfile()` → `lambda text, known_state=None, active_slot=None: {}`

Áp cho các test: `test_handle_user_message_returns_follow_up_when_score_missing`,
`test_handle_advisory_saves_pending_question`, `test_handle_advisory_clears_pending_question_when_complete`
(`{"total_score":25.0,"subject_combination":"A00","preferred_majors":["computer_science"],"location_preference":"Ha Noi"}`),
`test_handle_advisory_preserves_existing_profile_fields`, `test_ac_advisory_flow_unchanged`,
`test_pending_advisory_answer_via_llm_extracted_slot_continues_flow`
(`{"preferred_majors":["computer_science"]}`),
và các test pending-answer/bare-number (đa số `StudentProfile()` → `{}`).

- [ ] **Step 5: Chạy file conversation test, sửa tới khi xanh**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_conversation_service.py -v`
Expected: PASS. Các điểm cần khớp (đã trace):
- `test_bare_number_reply_fills_pending_total_score_slot`: `extract` trả `{}`, active_slot=`total_score`, safety-net parse `"29"` → `{total_score:29.0}` → continue điền slot. ✔
- `test_answering_pending_advisory_question_continues_flow_despite_misroute`: active_slot=`admission_year`, safety-net parse `2026`. ✔
- `test_interruption_during_pending_advisory_still_routes_to_knowledge`: delta `{}` + không parse được → not answered → rơi xuống KNOWLEDGE_QA. ✔
- Bất kỳ test nào còn assert giá trị merge: `apply_profile_delta` giữ field cũ + override field trong delta — tương đương kỳ vọng cũ.

- [ ] **Step 6: Chạy full suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: PASS toàn bộ. Nếu test ngoài conversation tham chiếu `merge_profile_state`/`parse_pending_slot_answer` từ conversation flow → chúng vẫn tồn tại trong `profile_state_service` (không xóa) nên không vỡ.

- [ ] **Step 7: Commit**

```bash
git add services/chat/conversation_service.py tests/services/chat/test_conversation_service.py
git commit -m "feat(chat): single delta extraction per turn with state-update + correction-aware merge (slice 3, G2/G3/G5)"
```

---

## Task 4: Dọn — bỏ đường dùng `merge_profile_state` trong conversation flow

**Files:**
- Modify: `services/chat/conversation_service.py` (xác nhận không còn import thừa)
- Modify: `services/chat/profile_state_service.py` (giữ `merge_profile_state` cho test unit của nó; thêm docstring "deprecated khỏi conversation flow")

- [ ] **Step 1: Rà import thừa**

Run (PowerShell): `Select-String -Path services/chat/conversation_service.py -Pattern "merge_profile_state|parse_pending_slot_answer|StudentProfile"`
Expected: không còn tham chiếu `merge_profile_state`/`parse_pending_slot_answer` trong `conversation_service.py`. Nếu còn import không dùng → xóa.

- [ ] **Step 2: Đánh dấu deprecated trong `profile_state_service.py`**

Thêm docstring vào `merge_profile_state`:

```python
def merge_profile_state(current: ChatProfileState, extracted: StudentProfile, raw_message: str) -> ChatProfileState:
    """DEPRECATED khỏi conversation flow (slice 3 dùng apply_profile_delta).
    Giữ lại cho test unit hiện có và tham chiếu ngoài."""
```

- [ ] **Step 3: Chạy full suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add services/chat/conversation_service.py services/chat/profile_state_service.py
git commit -m "chore(chat): drop merge_profile_state from conversation flow (slice 3)"
```

---

## Task 5: Verify end-to-end — đếm LLM call/lượt giảm

**Files:**
- Create: `tests/services/chat/test_turn_llm_budget.py`

- [ ] **Step 1: Viết test khẳng định fresh advisory turn = 1 extract + 1 classify (không double)**

Create `tests/services/chat/test_turn_llm_budget.py`:

```python
from types import SimpleNamespace

from services.chat.conversation_service import ConversationService
from services.chat.models import ChatProfileState, FlowState
from services.chat.intent_router import IntentResult


class _Repo:
    def __init__(self):
        self.profile_state = ChatProfileState()
        self.flow_state = FlowState(active_flow="ADVISORY_FLOW",
                                    pending_question="Bạn đang xét tuyển cho năm nào?")
        self.status = "collecting_profile"
        self.messages = []

    def append_message(self, *a):
        self.messages.append(a)

    def get_session_by_token(self, t):
        return SimpleNamespace(status=self.status)

    def get_profile_state(self, t):
        return self.profile_state

    def update_profile_state(self, t, p, s):
        self.profile_state = p
        self.status = s

    def get_flow_state(self, t):
        return self.flow_state

    def update_flow_state(self, t, f):
        self.flow_state = f


class _CountingRouter:
    def __init__(self):
        self.calls = 0

    def classify(self, message, profile_state):
        self.calls += 1
        return IntentResult(route="ADVISORY_FLOW")


def test_side_question_turn_extract_once_classify_once():
    extract_calls = {"n": 0}

    def extract(text, known_state=None, active_slot=None):
        extract_calls["n"] += 1
        return {}

    router = _CountingRouter()
    service = ConversationService(repository=_Repo(), extract_profile=extract, intent_router=router)
    service.handle_user_message("tok", "câu không điền slot")
    assert extract_calls["n"] == 1   # trước slice 3 có thể là 2
    assert router.calls == 1
```

- [ ] **Step 2: Chạy để xác nhận PASS**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_turn_llm_budget.py -v`
Expected: PASS — chứng minh G2 (1 extract/lượt).

- [ ] **Step 3: Commit**

```bash
git add tests/services/chat/test_turn_llm_budget.py
git commit -m "test(chat): regression — one extraction per turn (slice 3, G2)"
```

---

## Self-Review (đã thực hiện khi viết plan)

**Spec coverage (§7):** delta extractor + state-update + deterministic-first + skip-LLM (Task 1); correction-aware merge (Task 2); 1 extract/lượt, bỏ double-extract, wire delta (Task 3); dọn merge cũ (Task 4); regression G2 (Task 5). G2 ✔ G3 ✔ G5 ✔ (clear-to-empty là non-goal §10-D).

**Placeholder scan:** Không TBD/TODO; mọi step có code/command. ✔

**Type consistency:** `extract_profile_update(message, *, known_state, active_slot, gateway, resolver) -> dict`; `apply_profile_delta(current: ChatProfileState, delta: dict) -> ChatProfileState`; hợp đồng inject `extract_profile(text, known_state, active_slot) -> dict`; `_deterministic_safety_net(delta, content, active_slot)`; dùng nhất quán giữa code & test. ✔

**Rủi ro đã trace:** Các test conversation chuyển fake sang delta; hành vi bare-answer/admission_year được bảo toàn bằng `_deterministic_safety_net` (độc lập extractor inject). `merge_profile_state` giữ lại cho test unit của nó (không xóa).

---

## Tổng kết 3 slice

| Slice | Plan | Đạt |
|---|---|---|
| 1 | `…slice1-slot-registry.md` | G4 (slot 1 nguồn), subject_combination critical |
| 2 | `…slice2-major-catalog-resolver.md` | **G1** (thêm ngành không vỡ), catalog DB + tiered resolver |
| 3 | `…slice3-dst-extractor.md` | G2 (1 extract/lượt), G3 (state-update), G5 (correction merge) |

Có thể dừng sau Slice 2 mà vẫn giải quyết nỗi đau gốc (preferred_majors). G6 (degrade gracefully) trải đều cả 3 slice.
