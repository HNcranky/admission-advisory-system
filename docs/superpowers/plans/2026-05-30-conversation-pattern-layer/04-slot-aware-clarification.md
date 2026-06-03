# Plan 04 — Slot-Aware Clarification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `CLARIFICATION` hỏi đúng field còn thiếu (`school`/`programs`/`subject_combination`/`admission_year`) dựa trên `intent.missing_fields`, thay vì một câu chung chung; giữ câu chung làm safety net khi list rỗng.

**Architecture:** `_handle_clarification` nhận thêm `intent`, đọc `intent.missing_fields`, map field đầu tiên (theo thứ tự ưu tiên cố định) sang câu hỏi cụ thể qua hằng số `CLARIFICATION_PROMPTS`. Cập nhật dispatch để truyền `intent`.

**Tech Stack:** Python, pytest.

> **Convention test:** dùng `_make_service(intent_result=..., ...) -> (service, repo)` như Plan 03.
> `IntentResult` đã import sẵn trong test file.

**Phụ thuộc:** Plan 01 (field `missing_fields`).

> Project rule: bước "Commit" = chỉ `git add`, KHÔNG `git commit`. User tự commit.

---

### Task 1: `_handle_clarification` đọc `missing_fields`

**Files:**
- Modify: `services/chat/conversation_service.py:40-56` (dispatch — truyền `intent`)
- Modify: `services/chat/conversation_service.py:205-214` (`_handle_clarification`)
- Test: `tests/services/chat/test_conversation_service.py`

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/services/chat/test_conversation_service.py`:

```python
def test_clarification_asks_for_missing_school():
    service, repo = _make_service(
        intent_result=IntentResult(route="CLARIFICATION", missing_fields=["school"]),
    )
    result = service.handle_user_message("tok", "học phí trường này thế nào?")
    assert "trường nào" in result.assistant_message.lower()
    assert "nói rõ hơn câu hỏi" not in result.assistant_message


def test_clarification_asks_for_missing_subject_combination():
    service, repo = _make_service(
        intent_result=IntentResult(route="CLARIFICATION", missing_fields=["subject_combination"]),
    )
    result = service.handle_user_message("tok", "25 điểm thì chọn đâu?")
    assert "tổ hợp" in result.assistant_message.lower()


def test_clarification_falls_back_to_generic_when_no_missing_fields():
    service, repo = _make_service(
        intent_result=IntentResult(route="CLARIFICATION"),  # missing_fields=[]
    )
    result = service.handle_user_message("tok", "ý bạn là gì")
    assert "rõ hơn" in result.assistant_message.lower()
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_conversation_service.py -k clarification -v`
Expected: 2 test đầu FAIL (luôn trả câu generic). Test thứ 3 PASS sẵn. Test cũ
`test_handle_clarification_returns_clarification_request` vẫn PASS (route CLARIFICATION,
không missing_fields → generic chứa "rõ hơn").

- [ ] **Step 3: Thêm hằng số map field → câu hỏi**

Trong `services/chat/conversation_service.py`, thêm ở cấp module (sau phần import):

```python
CLARIFICATION_PROMPTS = {
    "school": "Bạn đang muốn tìm hiểu thông tin của trường nào?",
    "programs": "Bạn muốn so sánh hoặc tìm hiểu (những) ngành nào?",
    "subject_combination": "Bạn xét theo tổ hợp nào, ví dụ A00, A01 hay D01?",
    "admission_year": "Bạn đang xét tuyển cho năm nào?",
}
# Thứ tự ưu tiên khi có nhiều field thiếu.
CLARIFICATION_FIELD_ORDER = ["school", "programs", "subject_combination", "admission_year"]
GENERIC_CLARIFICATION = (
    "Bạn có thể nói rõ hơn câu hỏi của mình không? Mình muốn hiểu đúng để hỗ trợ tốt hơn."
)
```

- [ ] **Step 4: Cập nhật dispatch để truyền `intent`**

Trong `handle_user_message`, sửa dòng cuối:

```python
        return self._handle_clarification(
            session_token, intent, profile_state, flow_state, session_status
        )
```

- [ ] **Step 5: Viết lại `_handle_clarification`**

Thay thân method `_handle_clarification`:

```python
    def _handle_clarification(self, session_token, intent, profile_state, flow_state, session_status):
        msg = self._clarification_question(intent.missing_fields)
        response = self._append_return_prompt(msg, flow_state)
        self.repository.append_message(session_token, "assistant", response, "assistant_result")
        return ConversationTurnResult(
            session_status=session_status,
            assistant_message=response,
            should_start_run=False,
            profile_state=profile_state,
        )

    @staticmethod
    def _clarification_question(missing_fields) -> str:
        for field in CLARIFICATION_FIELD_ORDER:
            if field in (missing_fields or []):
                return CLARIFICATION_PROMPTS[field]
        return GENERIC_CLARIFICATION
```

- [ ] **Step 6: Chạy test để xác nhận PASS**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_conversation_service.py -k clarification -v`
Expected: tất cả PASS.

- [ ] **Step 7: Stage**

```bash
git add services/chat/conversation_service.py tests/services/chat/test_conversation_service.py
```

---

### Task 2: Regression toàn suite chat

- [ ] **Step 1: Chạy suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat -q`
Expected: tất cả PASS. Kiểm tra call site duy nhất của `_handle_clarification`
(trong `handle_user_message`) đã truyền `intent` — không còn nơi nào gọi với chữ ký cũ.

- [ ] **Step 2: Stage nếu cần**

```bash
git add -A services/chat tests/services/chat
```

---

## Self-review checklist
- [ ] Call site duy nhất của `_handle_clarification` đã truyền `intent`.
- [ ] `_clarification_question([])` → `GENERIC_CLARIFICATION` (test cũ `test_handle_clarification_returns_clarification_request` vẫn xanh).
- [ ] Thứ tự ưu tiên field cố định, không phụ thuộc thứ tự trong `missing_fields`.
- [ ] Không phá test conversational/knowledge/advisory/hybrid đã có.
