# Plan 03 — Wire CONVERSATIONAL Route Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nối route `CONVERSATIONAL` vào `ConversationService.handle_user_message` qua handler mới `_handle_conversational`, dùng `build_conversational_response` (Plan 02) và giữ hành vi resume hiện có (`_append_return_prompt`).

**Architecture:** Thêm một nhánh dispatch trong `handle_user_message` và một method `_handle_conversational` trong `services/chat/conversation_service.py`. Handler không chạy advisory run (`should_start_run=False`), persist message như các handler khác, dùng `seed=len(content)` để xoay biến thể template.

**Tech Stack:** Python, Pydantic v2, pytest.

> **Convention test (đã verify trong `tests/services/chat/test_conversation_service.py`):**
> dùng helper sẵn có `_make_service(intent_result=..., profile=..., flow=..., status=..., extract=..., knowledge_qa=...)`
> trả về `(service, repo)`. `repo` là `FakeRepository`: `repo.messages` là list các tuple
> `(role, kind, content)`; `repo.flow_state`, `repo.profile_state` truy cập trực tiếp.
> Đã import sẵn: `ConversationService`, `ChatProfileState`, `FlowState`, `IntentResult`,
> `Citation`, `KnowledgeQAResult`, `StudentProfile`. KHÔNG tạo helper mới.

**Phụ thuộc:** Plan 01 (route + subtype), Plan 02 (`conversational_handler`).

> Project rule: bước "Commit" = chỉ `git add`, KHÔNG `git commit`. User tự commit.

---

### Task 1: `_handle_conversational` + dispatch branch

**Files:**
- Modify: `services/chat/conversation_service.py:40-56` (dispatch trong `handle_user_message`)
- Modify: `services/chat/conversation_service.py` (thêm method mới, đặt sau `_handle_advisory`)
- Test: `tests/services/chat/test_conversation_service.py`

- [ ] **Step 1: Viết test thất bại cho greeting**

Thêm vào cuối `tests/services/chat/test_conversation_service.py`:

```python
def test_handle_conversational_greeting_returns_template_not_clarification():
    service, repo = _make_service(
        intent_result=IntentResult(route="CONVERSATIONAL", subtype="GREETING"),
    )
    result = service.handle_user_message("tok", "xin chào")

    assert result.should_start_run is False
    assert "nói rõ hơn câu hỏi" not in result.assistant_message
    # repo.messages entries are (role, kind, content)
    assistant_msgs = [m for m in repo.messages if m[0] == "assistant"]
    assert len(assistant_msgs) == 1


def test_handle_conversational_greeting_no_resume_when_no_active_flow():
    service, repo = _make_service(
        intent_result=IntentResult(route="CONVERSATIONAL", subtype="GREETING"),
        flow=FlowState(),  # active_flow=None
    )
    result = service.handle_user_message("tok", "xin chào")
    assert "Nhân tiện" not in result.assistant_message
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_conversation_service.py -k conversational -v`
Expected: FAIL — `handle_user_message` rơi vào nhánh cuối `_handle_clarification` (route không khớp nhánh nào) và trả câu "nói rõ hơn câu hỏi", assert vỡ.

- [ ] **Step 3: Thêm dispatch branch**

Trong `services/chat/conversation_service.py`, hàm `handle_user_message`, thêm nhánh ngay TRƯỚC dòng cuối `return self._handle_clarification(...)`:

```python
        if intent.route == "CONVERSATIONAL":
            return self._handle_conversational(
                session_token, content, intent, profile_state, flow_state, session_status
            )
```

- [ ] **Step 4: Thêm method `_handle_conversational`**

Thêm vào class `ConversationService` (đặt sau `_handle_advisory`):

```python
    def _handle_conversational(
        self, session_token, content, intent, profile_state, flow_state, session_status
    ):
        from services.chat.conversational_handler import build_conversational_response

        body = build_conversational_response(intent.subtype, seed=len(content))
        # _append_return_prompt chỉ gắn câu hỏi cũ khi đang có active advisory flow,
        # nên greeting lúc chưa có flow sẽ không bị nhắc resume.
        response = self._append_return_prompt(body, flow_state)
        self.repository.append_message(session_token, "assistant", response, "assistant_result")
        return ConversationTurnResult(
            session_status=session_status,
            assistant_message=response,
            should_start_run=False,
            profile_state=profile_state,
        )
```

- [ ] **Step 5: Chạy test để xác nhận PASS**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_conversation_service.py -k conversational -v`
Expected: PASS.

- [ ] **Step 6: Stage**

```bash
git add services/chat/conversation_service.py tests/services/chat/test_conversation_service.py
```

---

### Task 2: Greeting + nhu cầu rõ KHÔNG dừng ở greeting (regression an toàn)

> Quyết định route do LLM lo (Plan 01 prompt). Ở tầng service ta chỉ đảm bảo:
> khi router trả KNOWLEDGE_QA thì service KHÔNG đi vào nhánh conversational.

**Files:**
- Test: `tests/services/chat/test_conversation_service.py`

- [ ] **Step 1: Viết test**

Thêm vào `tests/services/chat/test_conversation_service.py`:

```python
def test_knowledge_route_not_handled_as_conversational():
    # FakeKnowledgeQA mặc định trả has_data=False → message no-data
    service, repo = _make_service(
        intent_result=IntentResult(route="KNOWLEDGE_QA", topic="tuition", school="VNU-UET"),
    )
    result = service.handle_user_message("tok", "Chào bạn, học phí UET?")

    assert "Chào bạn!" not in result.assistant_message          # không phải greeting template
    assert "chưa có dữ liệu" in result.assistant_message.lower()  # đi đúng nhánh knowledge
```

- [ ] **Step 2: Chạy test**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_conversation_service.py::test_knowledge_route_not_handled_as_conversational -v`
Expected: PASS (dispatch hiện có đã route KNOWLEDGE_QA đúng).

- [ ] **Step 3: Stage**

```bash
git add tests/services/chat/test_conversation_service.py
```

---

### Task 3: Regression toàn suite chat

- [ ] **Step 1: Chạy suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat -q`
Expected: tất cả PASS. Nhánh mới chỉ kích hoạt khi `route == "CONVERSATIONAL"` nên
không ảnh hưởng test cũ.

- [ ] **Step 2: Stage nếu có chỉnh sửa**

```bash
git add -A services/chat tests/services/chat
```

---

## Self-review checklist
- [ ] Nhánh `CONVERSATIONAL` nằm TRƯỚC `return self._handle_clarification(...)`.
- [ ] `_handle_conversational` trả `ConversationTurnResult` hợp lệ (có `profile_state`).
- [ ] `seed=len(content)` → biến thể xoay theo độ dài message.
- [ ] Greeting khi chưa có active_flow không chứa "Nhân tiện".
- [ ] Suite `tests/services/chat` xanh.
