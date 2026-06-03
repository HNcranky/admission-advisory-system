# Plan 02 — Conversational Handler Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tạo module thuần `services/chat/conversational_handler.py` sinh câu trả lời cho từng `subtype` hội thoại (greeting/thanks/goodbye/identity/capability/emotional) bằng template, deterministic để test ổn định.

**Architecture:** Module không chạm DB, không gọi LLM. Một hàm `build_conversational_response(subtype, seed)` trả về chuỗi; template là hằng số module; chọn biến thể bằng `variants[seed % len(variants)]` (deterministic). Việc persist message do `ConversationService` lo (Plan 03).

**Tech Stack:** Python, pytest.

> Project rule: bước "Commit" = chỉ `git add`, KHÔNG `git commit`. User tự commit.

---

### Task 1: Tạo module với greeting/thanks/goodbye/identity

**Files:**
- Create: `services/chat/conversational_handler.py`
- Test: `tests/services/chat/test_conversational_handler.py`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/services/chat/test_conversational_handler.py`:

```python
from services.chat.conversational_handler import build_conversational_response


def test_greeting_returns_nonempty_friendly_text():
    msg = build_conversational_response("GREETING", seed=0)
    assert msg
    assert "nói rõ hơn câu hỏi" not in msg


def test_greeting_is_deterministic_for_same_seed():
    a = build_conversational_response("GREETING", seed=3)
    b = build_conversational_response("GREETING", seed=3)
    assert a == b


def test_greeting_varies_across_seeds():
    seen = {build_conversational_response("GREETING", seed=i) for i in range(3)}
    assert len(seen) > 1  # có nhiều biến thể, không lặp một câu duy nhất


def test_thanks_and_goodbye_and_identity_return_text():
    for subtype in ("THANKS", "GOODBYE", "IDENTITY"):
        assert build_conversational_response(subtype, seed=0)
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_conversational_handler.py -v`
Expected: FAIL — `ModuleNotFoundError: services.chat.conversational_handler`.

- [ ] **Step 3: Tạo module (minimal cho 4 subtype này)**

Tạo `services/chat/conversational_handler.py`:

```python
from typing import List, Optional

_GREETING: List[str] = [
    "Chào bạn! Mình có thể giúp bạn tìm hiểu trường, ngành học hoặc thông tin tuyển sinh.",
    "Xin chào! Bạn đang muốn tìm hiểu trường, ngành hay phương thức xét tuyển nào?",
    "Chào bạn! Mình sẵn sàng giúp bạn tra cứu thông tin và cân nhắc lựa chọn phù hợp.",
]

_THANKS: List[str] = [
    "Rất vui được hỗ trợ bạn! Nếu cần thêm gì về tuyển sinh, cứ hỏi mình nhé.",
    "Không có gì đâu! Bạn còn muốn tìm hiểu thêm trường hay ngành nào không?",
]

_GOODBYE: List[str] = [
    "Chúc bạn ôn thi và xét tuyển thật tốt! Khi cần, mình luôn ở đây.",
    "Tạm biệt bạn nhé! Chúc bạn sớm chọn được trường, ngành ưng ý.",
]

_IDENTITY: List[str] = [
    "Mình là trợ lý tư vấn tuyển sinh đại học, giúp bạn tra cứu thông tin trường/ngành "
    "và cân nhắc lựa chọn dựa trên điểm số, nguyện vọng của bạn.",
]


def _pick(variants: List[str], seed: int) -> str:
    return variants[seed % len(variants)]


def build_conversational_response(subtype: Optional[str], seed: int = 0) -> str:
    if subtype == "GREETING":
        return _pick(_GREETING, seed)
    if subtype == "THANKS":
        return _pick(_THANKS, seed)
    if subtype == "GOODBYE":
        return _pick(_GOODBYE, seed)
    if subtype == "IDENTITY":
        return _pick(_IDENTITY, seed)
    raise ValueError(f"unsupported conversational subtype: {subtype!r}")
```

- [ ] **Step 4: Chạy test để xác nhận PASS**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_conversational_handler.py -v`
Expected: PASS.

- [ ] **Step 5: Stage**

```bash
git add services/chat/conversational_handler.py tests/services/chat/test_conversational_handler.py
```

---

### Task 2: Thêm CAPABILITY response

**Files:**
- Modify: `services/chat/conversational_handler.py`
- Test: `tests/services/chat/test_conversational_handler.py`

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/services/chat/test_conversational_handler.py`:

```python
def test_capability_describes_enabled_features():
    msg = build_conversational_response("CAPABILITY", seed=0)
    assert "tư vấn" in msg.lower()
    # mô tả đúng năng lực đang bật: advisory + tra cứu thông tin
    assert "học phí" in msg.lower() or "thông tin" in msg.lower()
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_conversational_handler.py::test_capability_describes_enabled_features -v`
Expected: FAIL — `ValueError: unsupported conversational subtype: 'CAPABILITY'`.

- [ ] **Step 3: Thêm hằng số + nhánh CAPABILITY**

Trong `services/chat/conversational_handler.py`, thêm hằng số (sau `_IDENTITY`):

```python
_CAPABILITY: str = (
    "Mình có thể giúp bạn tìm hiểu trường và ngành học, tra cứu các thông tin như "
    "học phí hoặc chương trình đào tạo khi hệ thống có nguồn dữ liệu, đồng thời hỗ "
    "trợ bạn cân nhắc lựa chọn phù hợp dựa trên điểm số và nhu cầu của bạn. "
    "Bạn muốn bắt đầu với trường hay ngành nào?"
)
```

Thêm nhánh trong `build_conversational_response` (trước `raise ValueError`):

```python
    if subtype == "CAPABILITY":
        return _CAPABILITY
```

- [ ] **Step 4: Chạy test để xác nhận PASS**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_conversational_handler.py -v`
Expected: PASS (cả test cũ).

- [ ] **Step 5: Stage**

```bash
git add services/chat/conversational_handler.py tests/services/chat/test_conversational_handler.py
```

---

### Task 3: Thêm EMOTIONAL_SUPPORT (đồng cảm + pivot advisory)

**Files:**
- Modify: `services/chat/conversational_handler.py`
- Test: `tests/services/chat/test_conversational_handler.py`

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/services/chat/test_conversational_handler.py`:

```python
def test_emotional_support_acknowledges_and_pivots():
    msg = build_conversational_response("EMOTIONAL_SUPPORT", seed=0)
    assert msg
    # có yếu tố chuyển sang bước advisory cụ thể (điểm/tổ hợp/ngành)
    low = msg.lower()
    assert "điểm" in low or "tổ hợp" in low or "ngành" in low
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_conversational_handler.py::test_emotional_support_acknowledges_and_pivots -v`
Expected: FAIL — `ValueError: unsupported conversational subtype: 'EMOTIONAL_SUPPORT'`.

- [ ] **Step 3: Thêm hằng số + nhánh**

Trong `services/chat/conversational_handler.py`, thêm hằng số:

```python
_EMOTIONAL_SUPPORT: str = (
    "Mình hiểu cảm giác lo lắng khi phải chọn trường và chờ kết quả. Nếu bạn chia "
    "sẻ điểm dự kiến, tổ hợp xét tuyển hoặc ngành quan tâm, mình có thể cùng bạn "
    "xem các lựa chọn thực tế hơn."
)
```

Thêm nhánh trong `build_conversational_response` (trước `raise ValueError`):

```python
    if subtype == "EMOTIONAL_SUPPORT":
        return _EMOTIONAL_SUPPORT
```

- [ ] **Step 4: Chạy test để xác nhận PASS**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_conversational_handler.py -v`
Expected: PASS.

- [ ] **Step 5: Stage**

```bash
git add services/chat/conversational_handler.py tests/services/chat/test_conversational_handler.py
```

---

## Self-review checklist
- [ ] Mọi subtype trong Literal của Plan 01 (`GREETING/CAPABILITY/THANKS/GOODBYE/IDENTITY/EMOTIONAL_SUPPORT`) đều có nhánh xử lý.
- [ ] `build_conversational_response` deterministic theo `seed`.
- [ ] Không import thừa, không chạm DB/LLM.
- [ ] `subtype=None` hoặc lạ → `raise ValueError` (để lỗi nổ rõ thay vì trả câu sai).
