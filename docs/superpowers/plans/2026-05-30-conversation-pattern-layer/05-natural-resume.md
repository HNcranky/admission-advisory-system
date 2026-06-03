# Plan 05 — Natural Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thay cơ chế resume máy móc (`_append_return_prompt` lặp lại nguyên `pending_question` ở mọi lượt off-topic) bằng một **câu offer resume tự nhiên** khi user rẽ sang CONVERSATIONAL/KNOWLEDGE_QA/OUT_OF_SCOPE/CLARIFICATION giữa advisory flow.

**Architecture:** Đổi `_append_return_prompt` → `_maybe_offer_resume`, thêm class attr `RESUME_OFFER`. Giữ điều kiện chỉ kích hoạt khi `flow_state.active_flow == "ADVISORY_FLOW"` và còn `pending_question`, nhưng KHÔNG lặp lại nguyên câu hỏi cũ. Cập nhật mọi call site. **Lưu ý:** "Nhân tiện, <follow_up>" trong `_handle_advisory` và `_handle_hybrid` là follow-up advisory hợp lệ (khác cơ chế resume) — KHÔNG đụng tới.

**Tech Stack:** Python, pytest.

> **Convention test:** `_make_service(...) -> (service, repo)`; `FlowState`, `IntentResult`,
> `ChatProfileState`, `Citation`, `KnowledgeQAResult` đã import sẵn. `FakeKnowledgeQA(result=...)`.

**Phụ thuộc:** Plan 03 (đã có `_handle_conversational`). Plan 04 (nếu xong) thì `_handle_clarification` cũng dùng helper này.

> Project rule: bước "Commit" = chỉ `git add`, KHÔNG `git commit`. User tự commit.

---

### Task 1: Đổi `_append_return_prompt` → `_maybe_offer_resume`

**Files:**
- Modify: `services/chat/conversation_service.py:216-225` (`_append_return_prompt`)
- Modify: các call site trong `services/chat/conversation_service.py`
- Test: `tests/services/chat/test_conversation_service.py`

- [ ] **Step 1: Thay 3 test helper trực tiếp đang có (sang kỳ vọng mới)**

Trong `tests/services/chat/test_conversation_service.py`, tìm khối "Task 3: _append_return_prompt"
(3 test: `test_append_return_prompt_adds_pending_question_when_in_advisory_flow`,
`test_append_return_prompt_skips_when_no_active_flow`,
`test_append_return_prompt_skips_when_no_pending_question`). **Thay cả 3** bằng:

```python
# ─── Resume offer (natural, không lặp câu hỏi cũ) ─────────────────────────────

def test_maybe_offer_resume_adds_offer_when_in_advisory_flow():
    service, _ = _make_service()
    flow = FlowState(active_flow="ADVISORY_FLOW", pending_question="Bạn học khối gì?")
    result = service._maybe_offer_resume("Xin lỗi, ngoài phạm vi.", flow)
    assert "Xin lỗi, ngoài phạm vi." in result
    assert service.RESUME_OFFER in result
    assert "Bạn học khối gì?" not in result  # KHÔNG lặp lại câu hỏi cũ


def test_maybe_offer_resume_skips_when_no_active_flow():
    service, _ = _make_service()
    flow = FlowState(active_flow=None, pending_question="Bạn học khối gì?")
    result = service._maybe_offer_resume("Xin lỗi, ngoài phạm vi.", flow)
    assert result == "Xin lỗi, ngoài phạm vi."


def test_maybe_offer_resume_skips_when_no_pending_question():
    service, _ = _make_service()
    flow = FlowState(active_flow="ADVISORY_FLOW", pending_question=None)
    result = service._maybe_offer_resume("Xin lỗi, ngoài phạm vi.", flow)
    assert result == "Xin lỗi, ngoài phạm vi."
```

- [ ] **Step 2: Chạy để xác nhận FAIL**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_conversation_service.py -k maybe_offer_resume -v`
Expected: FAIL — `AttributeError: 'ConversationService' object has no attribute '_maybe_offer_resume'` (và `RESUME_OFFER`).

- [ ] **Step 3: Viết lại helper trong `conversation_service.py`**

Thay method `_append_return_prompt` bằng:

```python
    RESUME_OFFER = "Bạn có muốn tiếp tục phần tư vấn lúc nãy không?"

    def _maybe_offer_resume(self, message: str, flow_state) -> str:
        """Offer quay lại advisory flow một cách tự nhiên khi user rẽ ngang.

        Chỉ kích hoạt khi đang giữa advisory flow (active_flow set và còn
        pending_question). KHÔNG lặp lại nguyên câu hỏi cũ — tránh cảm giác máy móc.
        """
        if flow_state.active_flow == "ADVISORY_FLOW" and flow_state.pending_question:
            return f"{message}\n\n{self.RESUME_OFFER}"
        return message
```

- [ ] **Step 4: Cập nhật mọi call site**

Đổi tất cả `self._append_return_prompt(...)` → `self._maybe_offer_resume(...)`.
Các vị trí: `_handle_knowledge_qa`, `_handle_out_of_scope`, `_handle_clarification`,
và `_handle_conversational` (từ Plan 03).

Xác nhận không còn tham chiếu tên cũ:

```powershell
Select-String -Path services/chat/conversation_service.py -Pattern "_append_return_prompt"
```
Expected: không có kết quả.

- [ ] **Step 5: Chạy test helper để xác nhận PASS**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_conversation_service.py -k maybe_offer_resume -v`
Expected: cả 3 PASS.

- [ ] **Step 6: Stage**

```bash
git add services/chat/conversation_service.py tests/services/chat/test_conversation_service.py
```

---

### Task 2: Cập nhật các test hành vi đang assert resume kiểu cũ

> Hai test sau hiện assert chuỗi "Nhân tiện" (= re-ask kiểu cũ) sinh ra TỪ resume
> helper. Sau Task 1 chúng sẽ vỡ và CẦN cập nhật. (Các test hybrid/advisory cũng có
> "Nhân tiện" nhưng đến từ follow-up inline trong `_handle_hybrid`/`_handle_advisory`,
> KHÔNG phải resume — để nguyên, chúng vẫn xanh.)

**Files:**
- Test: `tests/services/chat/test_conversation_service.py`

- [ ] **Step 1: Cập nhật `test_ac_reask_appears_on_first_detour`**

Tìm test này (route `OUT_OF_SCOPE`, assert `"Tổng điểm"` và `"Nhân tiện"`). Thay cả
hàm bằng:

```python
def test_ac_resume_offer_appears_on_first_detour():
    """Rẽ ngang khỏi advisory flow → offer quay lại tự nhiên, KHÔNG lặp câu hỏi cũ."""
    flow = FlowState(
        active_flow="ADVISORY_FLOW",
        pending_question="Tổng điểm hoặc mức điểm ước tính của bạn là bao nhiêu?",
    )
    service, _ = _make_service(
        intent_result=IntentResult(route="OUT_OF_SCOPE"),
        profile=ChatProfileState(preferred_majors=["computer_science"]),
        flow=flow,
    )
    result = service.handle_user_message("tok", "thời tiết hôm nay thế nào?")
    assert service.RESUME_OFFER in result.assistant_message
    assert "Tổng điểm" not in result.assistant_message  # không lặp câu hỏi cũ
```

- [ ] **Step 2: Cập nhật `test_knowledge_qa_data_answer_does_not_reset_profile_or_flow`**

Trong test này, đổi dòng cuối:

```python
    assert "Nhân tiện" in result.assistant_message  # mid-flow re-ask still appended
```

thành:

```python
    assert service.RESUME_OFFER in result.assistant_message  # mid-flow resume offer appended
```

(Giữ nguyên các assert còn lại: `repo.flow_state == flow`, `repo.profile_state.total_score == 25.0`.)

- [ ] **Step 3: Chạy 2 test này**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_conversation_service.py -k "resume_offer_appears or does_not_reset_profile_or_flow" -v`
Expected: PASS.

- [ ] **Step 4: Stage**

```bash
git add tests/services/chat/test_conversation_service.py
```

---

### Task 3: Regression toàn suite chat + e2e chat

- [ ] **Step 1: Chạy suite chat**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat -q`
Expected: tất cả PASS. Đặc biệt các test hybrid (`test_hybrid_incomplete_profile_*`) vẫn
xanh vì "Nhân tiện" của chúng đến từ `_handle_hybrid`, không phải resume helper.

- [ ] **Step 2: Chạy e2e chat (cần Docker DB nếu test yêu cầu)**

Run: `.\.venv\Scripts\python.exe -m pytest tests/e2e/test_chat_web_flow.py tests/e2e/test_chat_session_run_flow.py -q`
Expected: PASS hoặc skip nếu DB chưa lên. Nếu FAIL vì assert chứa câu re-ask cũ
("Nhân tiện, <câu hỏi>"), cập nhật expectation sang `ConversationService.RESUME_OFFER`.

- [ ] **Step 3: Stage**

```bash
git add -A services/chat tests
```

---

## Self-review checklist
- [ ] `Select-String ... "_append_return_prompt"` không còn kết quả (đã đổi hết call site).
- [ ] Resume offer chỉ xuất hiện khi `active_flow == "ADVISORY_FLOW"` và có `pending_question`.
- [ ] Response KHÔNG còn lặp lại nguyên `pending_question`.
- [ ] Greeting/knowledge khi chưa có flow → không có `RESUME_OFFER`.
- [ ] Test hybrid/advisory follow-up ("Nhân tiện, ...") không bị đụng và vẫn xanh.
- [ ] Suite `tests/services/chat` xanh; e2e chat xanh hoặc skip hợp lý.
