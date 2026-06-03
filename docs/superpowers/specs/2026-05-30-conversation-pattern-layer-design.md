# Conversation Pattern Layer — Design Spec

**Status:** Approved design, ready for planning
**Date:** 2026-05-30
**Scope:** `services/chat/` intent routing + handlers
**Related:** `docs/admission-advisory-conversational-architecture.md` (vision doc — note: ~50% already realized)

---

## 1. Mục tiêu

Agent hiện trả lời cứng nhắc với hội thoại thông thường (chào hỏi, hỏi năng lực,
cảm ơn) và dùng `CLARIFICATION` như một fallback chung chung. Spec này bổ sung
**delta thật sự còn thiếu** trên codebase hiện tại:

- **A.** Route `CONVERSATIONAL` + subtype + `ConversationalHandler`.
- **B.** Slot-aware clarification (hỏi đúng field thiếu thay vì câu chung).
- **C.** Resume tự nhiên (bỏ kiểu re-ask máy móc).

**Ngoài phạm vi (giữ nguyên):** Knowledge QA/RAG (`qa_service.py`), Hybrid
(`hybrid_dispatcher.py`, `synthesis_agent.py`), `OUT_OF_SCOPE`.
**Hoãn lại (không làm trong spec này):** capability-config dạng object đầy đủ,
telemetry schema, human handoff, rename `OUT_OF_SCOPE`.

---

## 2. Hiện trạng (đã verify trong code)

- Taxonomy: `ADVISORY_FLOW / KNOWLEDGE_QA / HYBRID / CLARIFICATION / OUT_OF_SCOPE`
  (`intent_router.py:59-61`). Không có route hội thoại thông thường.
- `_FALLBACK = ADVISORY_FLOW` (`intent_router.py:90`). Greeting không có nhãn →
  LLM đoán bừa (CLARIFICATION/OUT_OF_SCOPE/ADVISORY_FLOW tuỳ lúc).
- `_handle_clarification` trả về **một câu tĩnh duy nhất**
  (`conversation_service.py:205-206`).
- `flow_state` đã lưu `active_flow` + `pending_question`; `_append_return_prompt`
  (`conversation_service.py:216-225`) gắn "Nhân tiện, <câu hỏi cũ>" vào **mọi**
  lượt off-topic — đây là anti-pattern resume máy móc cần thay.
- Advisory flow đã có slot-aware follow-up qua `next_follow_up_question`
  (`profile_state_service.py:44-51`) nhưng route `CLARIFICATION` chưa tái dùng.

---

## 3. Phần A — Route CONVERSATIONAL

### 3.1. Mở rộng `IntentResult` (`intent_router.py`)

```python
route: Literal[
    "ADVISORY_FLOW", "KNOWLEDGE_QA", "HYBRID",
    "CLARIFICATION", "OUT_OF_SCOPE", "CONVERSATIONAL",  # added
]
subtype: Optional[Literal[
    "GREETING", "CAPABILITY", "THANKS", "GOODBYE", "IDENTITY", "EMOTIONAL_SUPPORT",
]] = None
missing_fields: List[str] = Field(default_factory=list)  # used by Part B
```

Các field mới có default an toàn → không đổi hành vi các route cũ.

### 3.2. Cập nhật `INTENT_SYSTEM_PROMPT`

Thêm mô tả route `CONVERSATIONAL` và quy tắc ưu tiên. Few-shots (rút từ vision
doc §10):

```
CONVERSATIONAL — chào hỏi, hỏi năng lực trợ lý, cảm ơn, tạm biệt, hỏi danh tính,
  hoặc bộc lộ cảm xúc/lo lắng về tuyển sinh. Trả thêm "subtype".

Quy tắc quan trọng:
- KHÔNG ép lời chào / cảm ơn / câu hỏi năng lực vào CLARIFICATION.
- CLARIFICATION chỉ khi đã hiểu user muốn gì nhưng thiếu entity bắt buộc.
- Nếu message vừa chào vừa có nhu cầu rõ ("Chào bạn, học phí UET?") → ưu tiên
  KNOWLEDGE_QA/ADVISORY_FLOW, KHÔNG dừng ở greeting.

Ví dụ:
"Xin chào"            → {"route":"CONVERSATIONAL","subtype":"GREETING"}
"Bạn giúp được gì?"   → {"route":"CONVERSATIONAL","subtype":"CAPABILITY"}
"Cảm ơn nhé"          → {"route":"CONVERSATIONAL","subtype":"THANKS"}
"Tạm biệt"            → {"route":"CONVERSATIONAL","subtype":"GOODBYE"}
"Bạn là ai?"          → {"route":"CONVERSATIONAL","subtype":"IDENTITY"}
"Mình lo không đỗ"    → {"route":"CONVERSATIONAL","subtype":"EMOTIONAL_SUPPORT"}
```

`_FALLBACK` giữ nguyên `ADVISORY_FLOW`.

### 3.3. `ConversationalHandler` mới (`services/chat/conversational_handler.py`)

Module thuần (template + một LLM-free response builder), không chạm DB. Trả về
chuỗi response; việc persist message do `conversation_service` lo (giữ đúng quy
ước "mỗi message một handler sinh final response").

- **GREETING / THANKS / GOODBYE / IDENTITY** — list template nhiều biến thể là
  hằng số module. Chọn biến thể **deterministic** theo độ dài lịch sử hội thoại
  (vd `variants[turn_count % len(variants)]`) — không dùng random để test ổn định.
- **CAPABILITY** — một câu mô tả năng lực đang bật, là hằng số module
  (`CAPABILITY_RESPONSE`). Không object config; nếu sau này cần bật/tắt theo
  trường thì refactor sau (YAGNI).
- **EMOTIONAL_SUPPORT** — template đồng cảm ngắn + pivot sang bước advisory cụ
  thể (vd "Nếu bạn chia sẻ điểm và tổ hợp, mình có thể cùng xem các lựa chọn
  thực tế hơn."). Không gọi LLM trong spec này.

Chữ ký gợi ý:

```python
def build_conversational_response(
    subtype: Optional[str],
    turn_count: int,
) -> str: ...
```

### 3.4. Wiring trong `conversation_service.py`

Thêm nhánh dispatch trong `handle_user_message`:

```python
if intent.route == "CONVERSATIONAL":
    return self._handle_conversational(session_token, intent, profile_state, flow_state, session_status)
```

`_handle_conversational` gọi `build_conversational_response`, áp dụng resume
logic ở Phần C, persist message, trả `ConversationTurnResult(should_start_run=False)`.

---

## 4. Phần B — Slot-aware clarification

### 4.1. Router populate `missing_fields`

Khi route `CLARIFICATION`, prompt yêu cầu trả `missing_fields` (vd `["school"]`,
`["programs"]`, `["subject_combination"]`). Đại từ "trường này" resolve được từ
profile → không phải CLARIFICATION.

### 4.2. `_handle_clarification` đọc missing field

Thay câu tĩnh bằng map field → câu hỏi cụ thể. Tái dùng từ vựng của
`next_follow_up_question` và bổ sung các field knowledge-context:

```python
CLARIFICATION_PROMPTS = {
    "school": "Bạn đang muốn tìm hiểu thông tin của trường nào?",
    "programs": "Bạn muốn so sánh/tìm hiểu (những) ngành nào?",
    "subject_combination": "Bạn xét theo tổ hợp nào, ví dụ A00, A01 hay D01?",
    "admission_year": "Bạn đang xét tuyển cho năm nào?",
}
```

- Có `missing_fields` → hỏi field đầu tiên (theo thứ tự ưu tiên cố định).
- Rỗng → mới fallback câu chung hiện tại (giữ làm safety net).

---

## 5. Phần C — Resume tự nhiên

### 5.1. Thay `_append_return_prompt`

Hành vi hiện tại lặp lại nguyên `pending_question` ở **mọi** lượt off-topic —
chính là anti-pattern vision doc §9 cảnh báo. Thay bằng:

- Khi `flow_state.active_flow == "ADVISORY_FLOW"` và lượt hiện tại là
  `CONVERSATIONAL` hoặc `KNOWLEDGE_QA`: sau khi trả lời nội dung chính, thêm
  **một câu offer resume tự nhiên** (không lặp nguyên câu hỏi cũ), vd:
  > "Bạn có muốn tiếp tục phần tư vấn lúc nãy không?"
- GREETING khi **chưa có** active_flow → không offer.
- THANKS/GOODBYE → không ép tiếp tục.
- `OUT_OF_SCOPE` mid-flow → vẫn có thể offer resume (giữ hành vi hữu ích).

### 5.2. Resume khi user đồng ý

Khi đang có active_flow và user trả lời thuận ("có", "tiếp đi") → router nên cho
ra `ADVISORY_FLOW`; handler advisory đọc `pending_question` để hỏi tiếp đúng bước.
(Hành vi này phần lớn đã đúng nhờ `flow_state` được giữ nguyên qua các lượt rẽ.)

---

## 6. Acceptance criteria

| Input | Context | Expected |
|---|---|---|
| "Xin chào" | — | `CONVERSATIONAL/GREETING`, không chứa "nói rõ hơn câu hỏi" |
| "Bạn giúp được gì?" | — | `CONVERSATIONAL/CAPABILITY`, chỉ mô tả năng lực đang bật |
| "Cảm ơn bạn" | — | `CONVERSATIONAL/THANKS` |
| "Bạn là ai?" | — | `CONVERSATIONAL/IDENTITY` |
| "Mình lo không đỗ UET" | — | `CONVERSATIONAL/EMOTIONAL_SUPPORT`, có pivot advisory |
| "Học phí trường này thế nào?" | no school | `CLARIFICATION`, `missing_fields=["school"]`, hỏi đúng trường |
| "Học phí trường này thế nào?" | school=VNU-UET | `KNOWLEDGE_QA/TUITION` (resolve được) |
| "Chào bạn, học phí UET?" | — | route theo KNOWLEDGE_QA, không dừng ở greeting |
| Knowledge question giữa advisory flow | active_flow set | trả lời knowledge + offer resume (không lặp nguyên câu hỏi cũ); flow không reset |

**Regression:**
- Thêm CONVERSATIONAL không giảm độ chính xác `ADVISORY_FLOW` / `KNOWLEDGE_QA` / `HYBRID`.
- Tuition/curriculum query không bị route nhầm thành CONVERSATIONAL.
- CLARIFICATION thật vẫn hỏi đúng slot.
- Mỗi message vẫn chỉ một handler sinh final response.

---

## 7. Files chạm tới

| File | Thay đổi |
|---|---|
| `services/chat/intent_router.py` | `IntentResult` + prompt + few-shots |
| `services/chat/conversational_handler.py` | **mới** — templates + response builder |
| `services/chat/conversation_service.py` | dispatch CONVERSATIONAL; rewrite `_handle_clarification`; thay `_append_return_prompt` bằng resume offer |
| `services/chat/profile_state_service.py` | (tuỳ chọn) export map prompt dùng chung cho clarification |
| `tests/` | unit cho router classification, ConversationalHandler, clarification slot-aware, resume |

---

## 8. Rủi ro

| Rủi ro | Giảm thiểu |
|---|---|
| Router phân loại sai greeting-kèm-nhu-cầu | Quy tắc ưu tiên + few-shot rõ trong prompt; regression test |
| Template lặp nhàm | Nhiều biến thể, xoay theo turn_count |
| Capability response hứa quá năng lực | Hằng số mô tả đúng năng lực đang bật; review thủ công |
| Resume offer gây phiền | Chỉ offer khi có active_flow; không ép, không lặp câu cũ |
