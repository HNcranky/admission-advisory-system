# Plan 01 — Router Schema & Prompt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mở rộng `IntentResult` để hỗ trợ route `CONVERSATIONAL` (kèm `subtype`) và `missing_fields`, đồng thời cập nhật prompt phân loại để không ép chào hỏi/cảm ơn vào `CLARIFICATION`.

**Architecture:** Chỉ chạm `services/chat/intent_router.py`. Thêm giá trị vào `Literal` của `route`, thêm 2 field mới với default an toàn (không đổi hành vi route cũ), và bổ sung mô tả + few-shots vào `INTENT_SYSTEM_PROMPT`. Gateway được stub trong test nên phần kiểm thử tập trung vào schema + passthrough, không kiểm thử hành vi LLM.

**Tech Stack:** Python, Pydantic v2, pytest.

> **Convention test (đã verify trong `tests/services/chat/test_intent_router.py`):** dùng helper sẵn có
> `_router(**kwargs)` = `IntentRouter(gateway=FakeGateway(**kwargs))`; `FakeGateway(parsed_data=...)`
> giả lập JSON LLM trả về; `ChatProfileState` đã import sẵn. KHÔNG tạo helper mới.

> Project rule: bước "Commit" = chỉ `git add`, KHÔNG `git commit`. User tự commit.

---

### Task 1: Mở rộng `IntentResult` với route CONVERSATIONAL + subtype + missing_fields

**Files:**
- Modify: `services/chat/intent_router.py:58-87` (class `IntentResult`)
- Test: `tests/services/chat/test_intent_router.py`

- [ ] **Step 1: Viết test thất bại cho route CONVERSATIONAL + subtype**

Thêm vào cuối `tests/services/chat/test_intent_router.py`:

```python
def test_classify_passes_through_conversational_subtype():
    r = _router(parsed_data={"route": "CONVERSATIONAL", "subtype": "GREETING"})
    result = r.classify("xin chào", ChatProfileState())
    assert result.route == "CONVERSATIONAL"
    assert result.subtype == "GREETING"
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_intent_router.py::test_classify_passes_through_conversational_subtype -v`
Expected: FAIL — gateway trả route `"CONVERSATIONAL"` không nằm trong `Literal` → `model_validate` ném ValidationError → `classify` rơi vào fallback `ADVISORY_FLOW`, assert `route == "CONVERSATIONAL"` vỡ. (Và `IntentResult` chưa có field `subtype`.)

- [ ] **Step 3: Cập nhật `IntentResult`**

Trong `services/chat/intent_router.py`, sửa class `IntentResult` (giữ nguyên các field `topic`, `school`, `schools`, `topics`, `needs_advisory`):

```python
class IntentResult(BaseModel):
    route: Literal[
        "ADVISORY_FLOW",
        "KNOWLEDGE_QA",
        "HYBRID",
        "CLARIFICATION",
        "OUT_OF_SCOPE",
        "CONVERSATIONAL",
    ]
    subtype: Optional[
        Literal[
            "GREETING",
            "CAPABILITY",
            "THANKS",
            "GOODBYE",
            "IDENTITY",
            "EMOTIONAL_SUPPORT",
        ]
    ] = None
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
    missing_fields: List[str] = Field(default_factory=list)
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

- [ ] **Step 4: Chạy test để xác nhận PASS**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_intent_router.py::test_classify_passes_through_conversational_subtype -v`
Expected: PASS

- [ ] **Step 5: Stage (user commit)**

```bash
git add services/chat/intent_router.py tests/services/chat/test_intent_router.py
```

---

### Task 2: Passthrough `missing_fields`

**Files:**
- Test: `tests/services/chat/test_intent_router.py`
- (Không cần sửa code — field đã thêm ở Task 1; task này khoá hành vi bằng test.)

- [ ] **Step 1: Viết test**

Thêm vào `tests/services/chat/test_intent_router.py`:

```python
def test_classify_passes_through_missing_fields():
    r = _router(parsed_data={"route": "CLARIFICATION", "missing_fields": ["school"]})
    result = r.classify("học phí trường này", ChatProfileState())
    assert result.route == "CLARIFICATION"
    assert result.missing_fields == ["school"]


def test_classify_missing_fields_defaults_empty():
    r = _router(parsed_data={"route": "ADVISORY_FLOW"})
    result = r.classify("25 điểm nên chọn ngành nào", ChatProfileState())
    assert result.missing_fields == []
```

- [ ] **Step 2: Chạy test**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_intent_router.py -k missing_fields -v`
Expected: PASS (field đã tồn tại với default `[]`). Nếu FAIL, kiểm tra lại Task 1 Step 3.

- [ ] **Step 3: Stage**

```bash
git add tests/services/chat/test_intent_router.py
```

---

### Task 3: Cập nhật `INTENT_SYSTEM_PROMPT` (mô tả CONVERSATIONAL + few-shots)

**Files:**
- Modify: `services/chat/intent_router.py:12-55` (`INTENT_SYSTEM_PROMPT`)

> Không có unit test cho nội dung prompt theo hành vi LLM (gateway bị stub). Có thể
> thêm 1 test "tài liệu hoá" giống `test_intent_prompt_documents_hybrid_payload` đã có.

- [ ] **Step 1: Viết test tài liệu hoá (khoá việc prompt có nhắc CONVERSATIONAL)**

Thêm vào `tests/services/chat/test_intent_router.py`:

```python
def test_intent_prompt_documents_conversational_route():
    from services.chat.intent_router import INTENT_SYSTEM_PROMPT
    assert "CONVERSATIONAL" in INTENT_SYSTEM_PROMPT
    assert "GREETING" in INTENT_SYSTEM_PROMPT
    assert "missing_fields" in INTENT_SYSTEM_PROMPT
```

- [ ] **Step 2: Chạy để xác nhận FAIL**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_intent_router.py::test_intent_prompt_documents_conversational_route -v`
Expected: FAIL — prompt chưa nhắc các từ này.

- [ ] **Step 3: Sửa prompt**

Trong `INTENT_SYSTEM_PROMPT`, đổi "đúng 1 trong 5 route" → "đúng 1 trong 6 route" và thêm khối mô tả `CONVERSATIONAL` ngay trước khối `ADVISORY_FLOW`:

```
CONVERSATIONAL — chào hỏi, hỏi năng lực trợ lý, cảm ơn, tạm biệt, hỏi danh tính,
  hoặc bộc lộ cảm xúc/lo lắng về tuyển sinh. Trả thêm "subtype":
  GREETING | CAPABILITY | THANKS | GOODBYE | IDENTITY | EMOTIONAL_SUPPORT
  Ví dụ: "xin chào", "bạn giúp được gì", "cảm ơn nhé", "tạm biệt", "bạn là ai",
         "mình lo không đỗ đại học"
```

Sau khối "Quy tắc resolve đại từ", thêm:

```
Quy tắc ưu tiên CONVERSATIONAL vs CLARIFICATION:
- KHÔNG ép lời chào / cảm ơn / câu hỏi năng lực vào CLARIFICATION.
- CLARIFICATION chỉ khi đã hiểu user muốn gì nhưng thiếu entity bắt buộc;
  khi đó trả thêm "missing_fields", ví dụ ["school"].
- Nếu message vừa chào vừa có nhu cầu rõ ("Chào bạn, học phí UET?") → ưu tiên
  KNOWLEDGE_QA/ADVISORY_FLOW, KHÔNG dừng ở greeting.

Few-shot CONVERSATIONAL & CLARIFICATION:
"Xin chào"            → {"route":"CONVERSATIONAL","subtype":"GREETING"}
"Bạn giúp được gì?"   → {"route":"CONVERSATIONAL","subtype":"CAPABILITY"}
"Cảm ơn nhé"          → {"route":"CONVERSATIONAL","subtype":"THANKS"}
"Tạm biệt"            → {"route":"CONVERSATIONAL","subtype":"GOODBYE"}
"Bạn là ai?"          → {"route":"CONVERSATIONAL","subtype":"IDENTITY"}
"Mình lo không đỗ"    → {"route":"CONVERSATIONAL","subtype":"EMOTIONAL_SUPPORT"}
"Học phí trường này?" (không có school trong profile)
                      → {"route":"CLARIFICATION","missing_fields":["school"]}
```

- [ ] **Step 4: Chạy lại toàn bộ test router**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_intent_router.py -q`
Expected: tất cả PASS.

- [ ] **Step 5: Verify thủ công (cần GEMINI key)**

Run:
```powershell
.\.venv\Scripts\python.exe -c "from services.chat.intent_router import IntentRouter; from services.chat.models import ChatProfileState; print(IntentRouter().classify('xin chào', ChatProfileState()).model_dump())"
```
Expected: dict có `'route': 'CONVERSATIONAL'`, `'subtype': 'GREETING'`. Nếu không có key → fallback `ADVISORY_FLOW` (chấp nhận, ghi chú verify lại sau).

- [ ] **Step 6: Stage**

```bash
git add services/chat/intent_router.py tests/services/chat/test_intent_router.py
```

---

## Self-review checklist
- [ ] `route` Literal có đúng 6 giá trị, `CONVERSATIONAL` nằm trong đó.
- [ ] `subtype` và `missing_fields` có default an toàn (`None` / `[]`).
- [ ] Các test cũ (`test_intent_result_*`, `test_classify_*`) vẫn PASS.
- [ ] `List`, `Optional`, `Literal`, `Field` đã import sẵn ở đầu file (không thêm import thừa).
