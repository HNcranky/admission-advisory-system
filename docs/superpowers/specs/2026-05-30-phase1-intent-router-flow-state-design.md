# Phase 1 — Intent Router & Flow State Preservation

**Date:** 2026-05-30
**Status:** Draft
**Parent spec:** `2026-05-30-intent-router-and-knowledge-qa-design.md`

---

## Problem

Hệ thống hiện tại chỉ có một luồng xử lý tuyến tính (`profile → retrieve → conflict → reason → policy → explain`). Mọi tin nhắn của user đều bị đẩy vào luồng tư vấn tuyển sinh bất kể nội dung.

Hệ quả:
- *"Học phí trường UET bao nhiêu?"* → hệ thống cố extract profile từ câu này → trả về câu hỏi tư vấn không liên quan
- *"Thời tiết hôm nay thế nào?"* → chạy toàn bộ advisory graph → lãng phí tài nguyên, trả lời sai
- Profile state bị reset hoặc nhiễu khi user hỏi câu bên lề giữa chừng

**Nguyên nhân gốc rễ:** Không có bước phân loại intent. `ConversationService` không biết phân biệt câu hỏi tư vấn với câu hỏi thực tế hoặc câu ngoài phạm vi.

---

## Mục đích Phase 1

Ngăn hệ thống ép câu hỏi bên lề vào luồng tư vấn. User nhận được hành vi đúng ngay lập tức **dù chưa có data RAG** (Phase 2–4 chưa hoàn thiện).

Sau Phase 1:
- Câu hỏi knowledge → trả fallback rõ ràng, không chạy advisory graph
- Câu ngoài phạm vi → từ chối lịch sự
- Profile state của user không bị ảnh hưởng khi rẽ nhánh
- Sau câu bên lề, agent tự động nhắc lại câu hỏi advisory đang chờ

---

## Phạm vi

**Trong scope:**
- `IntentRouter` service (LLM call riêng)
- `FlowState` model + DB migration
- Routing logic trong `ConversationService`
- Fallback responses cho KNOWLEDGE_QA và OUT_OF_SCOPE
- Re-ask mechanism sau khi trả lời câu bên lề
- Unit tests ≥ 20 cases

**Ngoài scope (Phase sau):**
- RAG pipeline thực sự cho KNOWLEDGE_QA (Phase 4)
- HYBRID orchestration (Phase 5)
- Corpus infrastructure (Phase 2–3)

---

## Files thay đổi

| File | Loại thay đổi |
|---|---|
| `services/chat/intent_router.py` | Tạo mới |
| `services/chat/models.py` | Thêm `FlowState`, `IntentResult` |
| `services/chat/conversation_service.py` | Sửa — thêm routing logic |
| `services/chat/repository.py` | Thêm `get_flow_state`, `update_flow_state` |
| `db/migrations/012_flow_state.sql` | Tạo mới |
| `tests/services/chat/test_intent_router.py` | Tạo mới |
| `tests/services/chat/test_conversation_service.py` | Mở rộng |
| `tests/services/chat/test_repository.py` | Mở rộng |

**Không thay đổi:** `graph.py`, `state.py`, toàn bộ agents, admission ingestion pipeline, structured data schema.

---

## Luồng xử lý mới

```
handle_user_message(session_token, content)
│
├── 1. save_message(content)
├── 2. profile_state = get_profile_state()       # đã có sẵn
│   flow_state    = get_flow_state()             # column mới
│
├── 3. intent = IntentRouter.classify(content, profile_state)
│             └── LLM call riêng, JSON output, ~200ms
│
├── 4a. route == ADVISORY_FLOW
│       → profile extraction → merge → next_follow_up_question
│       → IF có follow-up: set flow_state { active_flow=ADVISORY_FLOW, pending_question=<câu hỏi> }
│       → IF profile đủ: clear pending_question, should_start_run=True (graph.invoke() như cũ)
│
├── 4b. route == KNOWLEDGE_QA (+ HYBRID fallback Phase 1)
│       → return fallback message (HYBRID dùng chung vì đều cần dữ liệu knowledge)
│       → KHÔNG mutate flow_state, KHÔNG đụng profile
│       → IF đang dở advisory (active_flow + pending_question): append pending_question
│
├── 4c. route == OUT_OF_SCOPE
│       → return polite decline
│       → IF đang dở advisory (active_flow + pending_question): append pending_question
│
└── 4d. route == CLARIFICATION
        → return generic clarification request
        → IF đang dở advisory (active_flow + pending_question): append pending_question
```

Advisory graph (`graph.invoke()`) **không thay đổi** — chỉ được gọi khi `ADVISORY_FLOW` + profile đủ.

---

## 1. IntentRouter Service

**File:** `services/chat/intent_router.py`

### Output schema

```python
class IntentResult(BaseModel):
    route: Literal["ADVISORY_FLOW", "KNOWLEDGE_QA", "HYBRID", "CLARIFICATION", "OUT_OF_SCOPE"]
    topic: Optional[Literal[
        "tuition",          # học phí
        "curriculum",       # chương trình học
        "scholarship",      # học bổng
        "dormitory",        # ký túc xá
        "career",           # định hướng nghề nghiệp
        "admission_policy", # chính sách tuyển sinh
        "program_overview", # tổng quan chương trình
    ]] = None
    school: Optional[str] = None   # resolved từ message hoặc profile_state.preferred_schools
```

> **Lưu ý:** "user có đang dở advisory flow không" KHÔNG nằm trong `IntentResult` — nó là trạng thái tất định suy ra từ `FlowState` (xem §2), tính ở `ConversationService` chứ không bắt LLM đoán.

### Class

Tái dùng inference gateway sẵn có (giống `build_profile_with_gateway` trong `services/profile_inference_service.py`): gateway inject qua constructor (test không cần LLM thật), short-circuit khi `gateway.is_available()` false, và `classify()` bọc toàn bộ trong một `try/except Exception` nên không bao giờ raise.

```python
from services import build_default_gateway
from services.inference.models import InferenceRequest

_FALLBACK = IntentResult(route="ADVISORY_FLOW")

class IntentRouter:
    def __init__(self, gateway=None):
        self._gateway = gateway or build_default_gateway()

    def classify(self, message: str, profile_state: ChatProfileState) -> IntentResult:
        try:
            if hasattr(self._gateway, "is_available") and not self._gateway.is_available():
                return _FALLBACK
            result = self._gateway.run(InferenceRequest(
                agent_name="intent_router",
                task_type="intent_classification",
                system_prompt=INTENT_SYSTEM_PROMPT,
                user_prompt=self._build_user_prompt(message, profile_state),
                output_mode="json",
                temperature=0.0,
            ))
            if not result.parsed_data:
                return _FALLBACK
            return IntentResult.model_validate(result.parsed_data)
        except Exception:
            return _FALLBACK  # safe fallback: LLM throw / non-JSON / route không hợp lệ

    def _build_user_prompt(self, message: str, profile_state: ChatProfileState) -> str:
        ...   # xem "User turn" bên dưới
```

### System prompt

```
Bạn là bộ phân loại intent cho hệ thống tư vấn tuyển sinh đại học Việt Nam.

Phân loại tin nhắn của user vào đúng 1 trong 5 route:

ADVISORY_FLOW — câu hỏi tư vấn chọn ngành/trường dựa trên điểm số, nguyện vọng, khả năng đậu
  Ví dụ: "25 điểm A00 nên chọn trường nào", "em có đậu NEU không", "tư vấn ngành CNTT"

KNOWLEDGE_QA — câu hỏi thực tế về thông tin cụ thể của trường/ngành
  Ví dụ: "học phí UET bao nhiêu", "chương trình CNTT gồm gì", "có học bổng không", "ký túc xá thế nào"

CLARIFICATION — câu quá mơ hồ, thiếu context để phân loại chính xác
  Ví dụ: "thế còn cái đó thì sao" (không rõ "cái đó" là gì), "ý bạn là gì"

OUT_OF_SCOPE — hoàn toàn ngoài lĩnh vực tuyển sinh đại học
  Ví dụ: "thời tiết hôm nay", "kể chuyện cười", "1+1 bằng mấy", "giúp tôi viết code"

HYBRID — cần cả dữ liệu tư vấn (điểm chuẩn, xác suất đậu) lẫn thông tin thực tế (học phí, chương trình)
  Ví dụ: "so sánh UET và HUST về điểm chuẩn lẫn học phí"
  Lưu ý: chỉ dùng HYBRID khi thực sự cần cả hai loại dữ liệu, không dùng cho câu hỏi thuần advisory

Quy tắc resolve đại từ:
- Nếu user dùng "trường này", "ở đó", "trường đó" → resolve từ preferred_schools trong profile
- Nếu user dùng "ngành này", "chuyên ngành đó" → resolve từ preferred_majors trong profile
- Nếu không thể resolve → để school/topic là null, route về CLARIFICATION

Trường (school): chuẩn hóa thành tên viết tắt phổ biến (VNU-UET, HUST, NEU, ...) nếu nhận ra.

Trả về JSON hợp lệ theo schema sau, không giải thích thêm:
{"route": "...", "topic": "...", "school": "..."}
```

### User turn

```
Tin nhắn: "{message}"

Profile hiện tại:
- Trường quan tâm: {preferred_schools or "chưa có"}
- Ngành quan tâm: {preferred_majors or "chưa có"}
- Điểm số: {total_score or "chưa có"}
- Khối thi: {subject_combination or "chưa có"}
```

### Error handling

| Tình huống | Hành vi |
|---|---|
| LLM call throw | Trả `IntentResult(route="ADVISORY_FLOW")` |
| Response không parse được thành JSON | Trả `IntentResult(route="ADVISORY_FLOW")` |
| `route` không hợp lệ | Trả `IntentResult(route="ADVISORY_FLOW")` |
| `school=null` trong KNOWLEDGE_QA | Service dùng label *"trường bạn hỏi"* |
| `topic=null` trong KNOWLEDGE_QA | Service dùng label *"thông tin này"* |

Không propagate exception ra ngoài `classify()`.

---

## 2. FlowState Model

**Thêm vào** `services/chat/models.py`:

```python
class FlowState(BaseModel):
    active_flow:      Optional[str] = None   # "ADVISORY_FLOW" khi đang trong luồng tư vấn
    pending_question: Optional[str] = None  # follow-up question cuối cùng đã hỏi user
```

> **Bỏ `return_to_flow`:** "user có đang dở advisory flow không" suy được tất định từ `active_flow == "ADVISORY_FLOW" and pending_question is not None`. Giữ thêm một cờ riêng vừa thừa vừa gây bug off-by-one (cờ bị set *sau* khi đã build response). Toàn bộ logic re-ask dựa trực tiếp vào 2 field trên.

### Lifecycle

| Sự kiện | Thay đổi FlowState |
|---|---|
| Session mới | `{}` — default (tất cả None) |
| ADVISORY turn, trả follow-up question | `active_flow="ADVISORY_FLOW"`, `pending_question=<câu hỏi>` |
| ADVISORY turn, profile đủ (run bắt đầu) | `active_flow="ADVISORY_FLOW"`, `pending_question=None` (clear) |
| KNOWLEDGE_QA / OUT_OF_SCOPE / CLARIFICATION turn | **Không mutate** — chỉ đọc để quyết định có re-ask không |
| Trả lời xong câu bên lề, user quay lại advisory | Handled bình thường bởi ADVISORY_FLOW branch |

Vì câu detour không mutate flow state, `pending_question` đã được persist từ lượt advisory trước đó, nên re-ask xuất hiện **ngay từ câu bên lề đầu tiên** (sửa bug off-by-one).

---

## 3. DB Migration

**File:** `db/migrations/012_flow_state.sql`

```sql
-- Thêm column lưu flow control state, tách biệt với profile data
ALTER TABLE chat_sessions
    ADD COLUMN IF NOT EXISTS flow_state_json JSONB NOT NULL DEFAULT '{}';
```

Idempotent (`ADD COLUMN IF NOT EXISTS`). Không đụng đến column hiện có. Default `'{}'` tương thích với `FlowState()` default.

---

## 4. Repository Changes

**Thêm vào** `services/chat/repository.py`:

Bám đúng pattern hiện có của repository: tuple cursor (`row[0]`, không phải `row["..."]`), wrap JSONB bằng `self._jsonb(...)`, tự mở/commit/đóng connection. `FlowState(**dict)` giống cách `get_profile_state` dựng `ChatProfileState`.

```python
def get_flow_state(self, session_token: str) -> FlowState:
    conn = self.connection_factory()
    cur = conn.cursor()
    cur.execute(
        "SELECT flow_state_json FROM chat_sessions WHERE session_token = %s",
        (session_token,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return FlowState()
    return FlowState(**(row[0] or {}))

def update_flow_state(self, session_token: str, flow_state: FlowState) -> None:
    conn = self.connection_factory()
    cur = conn.cursor()
    cur.execute(
        "UPDATE chat_sessions SET flow_state_json = %s, updated_at = NOW() WHERE session_token = %s",
        (self._jsonb(flow_state), session_token),
    )
    conn.commit()
    cur.close()
    conn.close()
```

Không swallow exception — DB failure propagate lên caller.

---

## 5. ConversationService Changes

`handle_user_message()` tách thành private methods. `IntentRouter` injectable qua constructor để test.

```python
class ConversationService:
    def __init__(self, repository=None, extract_profile=None, intent_router=None):
        self.repository   = repository    or ChatSessionRepository()
        self.extract_profile = extract_profile or self._extract_profile
        self.intent_router = intent_router or IntentRouter()

    # ------------------------------------------------------------------ public

    def handle_user_message(self, session_token: str, content: str) -> ConversationTurnResult:
        self.repository.append_message(session_token, "user", content, kind="user_message")
        session       = self.repository.get_session_by_token(session_token)
        profile_state = self.repository.get_profile_state(session_token)
        flow_state    = self.repository.get_flow_state(session_token)
        intent        = self.intent_router.classify(content, profile_state)

        if intent.route == "ADVISORY_FLOW":
            return self._handle_advisory(session_token, content, profile_state, flow_state)
        # HYBRID chưa implement orchestration → Phase 1 dùng chung knowledge fallback
        # (câu vốn rõ ràng, trả "chưa có dữ liệu" hợp lý hơn đòi user clarify)
        if intent.route in ("KNOWLEDGE_QA", "HYBRID"):
            return self._handle_knowledge_qa(session_token, intent, profile_state, flow_state, session.status)
        if intent.route == "OUT_OF_SCOPE":
            return self._handle_out_of_scope(session_token, profile_state, flow_state, session.status)
        return self._handle_clarification(session_token, profile_state, flow_state, session.status)

    # ----------------------------------------------------------------- private

    def _handle_advisory(self, session_token, content, profile_state, flow_state):
        # Logic hiện tại giữ nguyên: extract → merge → next_follow_up_question → follow-up | run
        extracted = self.extract_profile(content)
        merged    = merge_profile_state(profile_state, extracted, content)

        follow_up = next_follow_up_question(merged)
        if follow_up:
            self.repository.update_profile_state(session_token, merged, "collecting_profile")
            self.repository.update_flow_state(
                session_token,
                flow_state.model_copy(update={
                    "active_flow": "ADVISORY_FLOW",
                    "pending_question": follow_up,
                }),
            )
            self.repository.append_message(session_token, "assistant", follow_up, kind="assistant_follow_up")
            return ConversationTurnResult(
                session_status="collecting_profile",
                assistant_message=follow_up,
                should_start_run=False,
                profile_state=merged,
            )

        ready_message = "Cảm ơn bạn. Mình đã có đủ thông tin và sẽ bắt đầu phân tích."
        self.repository.update_profile_state(session_token, merged, "ready")
        self.repository.update_flow_state(
            session_token,
            flow_state.model_copy(update={
                "active_flow": "ADVISORY_FLOW",
                "pending_question": None,   # clear: không còn câu chờ
            }),
        )
        self.repository.append_message(session_token, "assistant", ready_message, kind="assistant_ready")
        return ConversationTurnResult(
            session_status="ready",
            assistant_message=ready_message,
            should_start_run=True,
            profile_state=merged,
        )

    def _handle_knowledge_qa(self, session_token, intent, profile_state, flow_state, session_status):
        # Phase 1: chưa có RAG data → luôn trả fallback. KHÔNG đụng profile, KHÔNG mutate flow_state.
        TOPIC_LABELS = {
            "tuition": "học phí", "curriculum": "chương trình học",
            "scholarship": "học bổng", "dormitory": "ký túc xá",
            "career": "định hướng nghề nghiệp", "admission_policy": "chính sách tuyển sinh",
            "program_overview": "tổng quan chương trình",
        }
        topic_label  = TOPIC_LABELS.get(intent.topic, "thông tin này")
        school_label = intent.school or "trường bạn hỏi"

        fallback = (
            f"Hệ thống chưa có dữ liệu về {topic_label} của {school_label}. "
            f"Bạn có thể liên hệ trực tiếp nhà trường để biết thêm chi tiết."
        )
        response = self._append_return_prompt(fallback, flow_state)
        self.repository.append_message(session_token, "assistant", response, kind="assistant_result")
        return ConversationTurnResult(
            session_status=session_status,
            assistant_message=response,
            should_start_run=False,
            profile_state=profile_state,
        )

    def _handle_out_of_scope(self, session_token, profile_state, flow_state, session_status):
        msg = (
            "Xin lỗi, câu hỏi này nằm ngoài phạm vi tư vấn tuyển sinh của mình. "
            "Mình chỉ có thể hỗ trợ các vấn đề liên quan đến tuyển sinh đại học."
        )
        response = self._append_return_prompt(msg, flow_state)
        self.repository.append_message(session_token, "assistant", response, kind="assistant_result")
        return ConversationTurnResult(
            session_status=session_status,
            assistant_message=response,
            should_start_run=False,
            profile_state=profile_state,
        )

    def _handle_clarification(self, session_token, profile_state, flow_state, session_status):
        msg = "Bạn có thể nói rõ hơn câu hỏi của mình không? Mình muốn hiểu đúng để hỗ trợ tốt hơn."
        response = self._append_return_prompt(msg, flow_state)
        self.repository.append_message(session_token, "assistant", response, kind="assistant_result")
        return ConversationTurnResult(
            session_status=session_status,
            assistant_message=response,
            should_start_run=False,
            profile_state=profile_state,
        )

    def _append_return_prompt(self, message: str, flow_state: FlowState) -> str:
        """Nếu user đang dở advisory flow (active_flow + pending_question) → nhắc lại cuối response."""
        if flow_state.active_flow == "ADVISORY_FLOW" and flow_state.pending_question:
            return f"{message}\n\nNhân tiện, {flow_state.pending_question}"
        return message
```

> **Import bổ sung** (cùng module `conversation_service.py`):
> `from services.chat.profile_state_service import merge_profile_state, next_follow_up_question`
> `from services.chat.intent_router import IntentRouter`
>
> **Số DB write mỗi lượt advisory:** `update_profile_state` + `update_flow_state` là 2 transaction tách (mỗi repo method tự mở/đóng connection). Chấp nhận được ở Phase 1; nếu cần atomic sau này, gộp 2 update vào một câu lệnh `UPDATE ... SET profile_state_json=..., flow_state_json=..., status=...`.

---

## 6. Error Handling

| Tình huống | Hành vi |
|---|---|
| `IntentRouter.classify()` throw | Đã tự catch bên trong, trả `ADVISORY_FLOW` |
| `route="HYBRID"` (chưa implement) | Fallback `_handle_knowledge_qa()` — câu HYBRID rõ ràng, trả "chưa có dữ liệu" thay vì đòi clarify |
| `get_flow_state()` DB lỗi | Propagate — không swallow |
| `update_flow_state()` DB lỗi | Propagate — không swallow |
| `school=null` trong KNOWLEDGE_QA | Label *"trường bạn hỏi"* |
| `topic=null` trong KNOWLEDGE_QA | Label *"thông tin này"* |

---

## 7. Testing Strategy

### `tests/services/chat/test_intent_router.py` — unit tests (mock LLM)

≥ 20 cases bao phủ 5 routes:

**ADVISORY_FLOW (≥ 5 cases):**
- `"25 điểm A00 nên chọn trường nào"` → ADVISORY_FLOW
- `"em có đậu NEU không"` → ADVISORY_FLOW
- `"tư vấn ngành CNTT cho mình"` → ADVISORY_FLOW
- `"điểm 28 khối B00 nên nộp đâu"` → ADVISORY_FLOW
- `"cơ hội đậu Bách Khoa của em là bao nhiêu"` → ADVISORY_FLOW

**KNOWLEDGE_QA (≥ 5 cases):**
- `"học phí UET bao nhiêu"` → KNOWLEDGE_QA, topic=tuition, school=VNU-UET
- `"chương trình học CNTT gồm gì"` → KNOWLEDGE_QA, topic=curriculum
- `"có học bổng không"` → KNOWLEDGE_QA, topic=scholarship
- `"ký túc xá thế nào"` → KNOWLEDGE_QA, topic=dormitory
- `"trường này học phí bao nhiêu"` + `preferred_schools=["VNU-UET"]` → school=VNU-UET

**OUT_OF_SCOPE (≥ 4 cases):**
- `"thời tiết hôm nay thế nào"` → OUT_OF_SCOPE
- `"kể cho tôi nghe một câu chuyện cười"` → OUT_OF_SCOPE
- `"giúp tôi viết code Python"` → OUT_OF_SCOPE
- `"hôm nay ăn gì ngon"` → OUT_OF_SCOPE

**CLARIFICATION (≥ 3 cases):**
- `"thế còn cái đó thì sao"` (no profile) → CLARIFICATION
- `"ý bạn là gì"` → CLARIFICATION
- `"còn nữa không"` (no context) → CLARIFICATION

**LLM failure (≥ 3 cases):**
- LLM throw exception → fallback ADVISORY_FLOW
- LLM trả về non-JSON → fallback ADVISORY_FLOW
- LLM trả về route không hợp lệ → fallback ADVISORY_FLOW

### `tests/services/chat/test_conversation_service.py` — mở rộng file hiện có

Dùng `FakeIntentRouter` inject vào constructor:

```python
class FakeIntentRouter:
    def __init__(self, result: IntentResult):
        self._result = result
    def classify(self, message, profile_state):
        return self._result
```

Cases:
- Route ADVISORY_FLOW → `_handle_advisory` chạy, profile được update
- Route KNOWLEDGE_QA → trả fallback message, profile **không bị reset**, flow_state **không bị mutate**
- Route HYBRID → đi vào `_handle_knowledge_qa` (Phase 1 fallback), trả "chưa có dữ liệu"
- Route OUT_OF_SCOPE → trả polite decline, profile **không bị reset**
- Route CLARIFICATION → trả generic clarification
- `active_flow="ADVISORY_FLOW"` + `pending_question="Bạn học khối gì?"`, rẽ KNOWLEDGE_QA → câu nhắc xuất hiện cuối response **ngay câu detour đầu tiên** (regression test cho bug off-by-one)
- `active_flow=None` (chưa vào advisory) + detour → KHÔNG append gì thêm
- `pending_question=None` + detour → KHÔNG append gì thêm
- `flow_state.pending_question` được lưu khi ADVISORY follow-up
- `flow_state.pending_question` giữ nguyên khi rẽ KNOWLEDGE_QA (detour không ghi flow_state)
- `flow_state.pending_question` cleared (`=None`) khi profile đủ, `should_start_run=True`
- Mọi branch off-topic trả `ConversationTurnResult` hợp lệ (đủ `session_status`, `assistant_message`, `profile_state`) — không raise ValidationError

### `tests/services/chat/test_repository.py` — mở rộng

- `get_flow_state()` trả `FlowState()` default khi column là `{}`
- `update_flow_state()` + `get_flow_state()` round-trip đúng (persist và đọc lại)

---

## Acceptance Criteria

- [ ] `"học phí UET bao nhiêu?"` → route `KNOWLEDGE_QA`, **KHÔNG** chạy advisory graph
- [ ] `"Em 25 điểm A00 nên chọn ngành gì?"` → route `ADVISORY_FLOW`, flow hiện tại không thay đổi
- [ ] `"thời tiết hôm nay thế nào?"` → route `OUT_OF_SCOPE`, trả lời lịch sự
- [ ] `KNOWLEDGE_QA` chưa có data → *"Hệ thống chưa có dữ liệu về [topic] của [trường], bạn có thể liên hệ trực tiếp nhà trường..."*
- [ ] Đang dở advisory (`active_flow="ADVISORY_FLOW"` + `pending_question` đã set) → **ngay câu bên lề đầu tiên**, response kết thúc bằng pending follow-up question
- [ ] Profile state của user **KHÔNG bị reset** và flow_state **KHÔNG bị mutate** khi route sang nhánh off-topic
- [ ] Mọi nhánh trả `ConversationTurnResult` đủ field bắt buộc (`session_status`, `assistant_message`, `profile_state`)
- [ ] Unit test router ≥ 20 cases bao phủ 5 intent types
- [ ] Migration idempotent — chạy lại không lỗi, không duplicate column
