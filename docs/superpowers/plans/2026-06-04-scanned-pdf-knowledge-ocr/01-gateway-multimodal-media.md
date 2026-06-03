# Plan 01: Gateway Multimodal Media Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cho phép `InferenceRequest` mang ảnh (PNG bytes) để `GeminiProvider` gửi call đa phương thức (vision), không ảnh hưởng bất kỳ call site text-only nào hiện có.

**Architecture:** Thêm field `media: List[Tuple[str, bytes]]` (mime, raw bytes) mặc định rỗng vào `InferenceRequest`; trong `GeminiProvider._call`, nếu `media` không rỗng thì build `contents=[Part.from_bytes(...), user_prompt]`, ngược lại giữ nguyên `contents=user_prompt`. Đăng ký 2 agent mới (`knowledge_ocr`, `knowledge_classify`) vào `build_default_gateway()`. Gateway/registry/key-pool/telemetry không đổi.

**Tech Stack:** Pydantic v2, `google-genai` (`types.Part.from_bytes`), pytest với FakeClient/GeminiKeyPool sẵn có.

**Phụ thuộc:** Không. Đây là plan nền cho Plan 02 (OCR) và Plan 03 (classify).

---

## Bối cảnh cho người chưa biết codebase

- Mọi LLM call đi qua `LLMGateway.run(InferenceRequest)` (`services/inference/gateway.py`).
  Gateway resolve policy theo `agent_name` từ `ModelRegistry` (`services/inference/registry.py`),
  rồi gọi `GeminiProvider.generate(request, policy)`.
- `GeminiProvider._call` (`services/inference/providers/gemini_provider.py:36-47`) hiện
  truyền `contents=request.user_prompt` (string) vào `client.models.generate_content`.
- Test provider dùng `FakeClient`/`FakeModels` capture kwargs (`tests/services/inference/test_gemini_provider.py:29-51`) — **không network**.
- Pydantic trong repo là **v2**: field mới có default ⇒ call site cũ không cần sửa.

---

### Task 1: Field `media` trên `InferenceRequest`

**Files:**
- Modify: `services/inference/models.py:10-18`
- Test: `tests/services/inference/test_gemini_provider.py` (thêm vào cuối file)

- [ ] **Step 1: Viết failing test**

Thêm vào cuối `tests/services/inference/test_gemini_provider.py`:

```python
# --- multimodal media ----------------------------------------------------------

def test_inference_request_media_defaults_to_empty_list():
    # Call site cũ không truyền media → field phải tồn tại và rỗng.
    request = _request()
    assert request.media == []


def test_inference_request_accepts_media_tuples():
    request = InferenceRequest(
        agent_name="knowledge_ocr",
        task_type="page_ocr",
        system_prompt="sys",
        user_prompt="usr",
        media=[("image/png", b"\x89PNG")],
    )
    assert request.media == [("image/png", b"\x89PNG")]
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests\services\inference\test_gemini_provider.py -q -k media`
Expected: 2 FAILED với `AttributeError: 'InferenceRequest' object has no attribute 'media'` (Pydantic v2 mặc định ignore kwarg lạ nên construct vẫn thành công, đọc attribute mới fail).

- [ ] **Step 3: Thêm field vào model**

Sửa `services/inference/models.py` — đổi dòng import và thêm field vào `InferenceRequest`:

```python
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field


class InferenceError(RuntimeError):
    """Raised when the inference provider hits a hard failure (network, auth, rate limit)."""


class InferenceRequest(BaseModel):
    agent_name: str
    task_type: str
    system_prompt: str
    user_prompt: str
    output_mode: str = "free_text"
    schema_name: Optional[str] = None
    temperature: float = 0.0
    # (mime_type, raw_bytes) attachments for multimodal (vision) calls.
    # Default empty => every existing text-only call site is unaffected.
    media: List[Tuple[str, bytes]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
```

(`InferencePolicy` và `InferenceResult` phía dưới giữ nguyên.)

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests\services\inference\test_gemini_provider.py -q`
Expected: tất cả PASS (cả test cũ lẫn 2 test mới).

- [ ] **Step 5: Commit**

```powershell
git add services\inference\models.py tests\services\inference\test_gemini_provider.py
git commit -m "feat: add media field to InferenceRequest for multimodal calls"
```

---

### Task 2: Nhánh multimodal trong `GeminiProvider._call`

**Files:**
- Modify: `services/inference/providers/gemini_provider.py:36-47`
- Test: `tests/services/inference/test_gemini_provider.py` (thêm vào cuối file)

- [ ] **Step 1: Viết failing test**

Thêm vào cuối `tests/services/inference/test_gemini_provider.py`:

```python
def test_media_request_builds_multimodal_contents():
    captured = {}
    pool = _pool({"k1": FakeClient(text="# OCR markdown", captured=captured)})
    provider = GeminiProvider(pool=pool)
    request = InferenceRequest(
        agent_name="knowledge_ocr",
        task_type="page_ocr",
        system_prompt="sys",
        user_prompt="usr",
        output_mode="free_text",
        temperature=0.0,
        media=[("image/png", b"\x89PNG-bytes")],
    )

    result = provider.generate(request, _policy(agent="knowledge_ocr"))

    contents = captured["contents"]
    assert isinstance(contents, list)
    assert contents[-1] == "usr"                       # prompt đứng SAU ảnh
    part = contents[0]                                 # google.genai types.Part
    assert part.inline_data.mime_type == "image/png"
    assert part.inline_data.data == b"\x89PNG-bytes"
    assert result.content == "# OCR markdown"


def test_request_without_media_keeps_plain_string_contents():
    # Regression: hành vi cũ nguyên vẹn khi không có media.
    captured = {}
    pool = _pool({"k1": FakeClient(text="hello", captured=captured)})
    provider = GeminiProvider(pool=pool)

    provider.generate(_request(output_mode="free_text"), _policy())

    assert captured["contents"] == "usr"
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests\services\inference\test_gemini_provider.py -q -k "multimodal or plain_string"`
Expected: `test_media_request_builds_multimodal_contents` FAILED với `AssertionError` tại `isinstance(contents, list)` (provider cũ vẫn truyền string). `test_request_without_media_keeps_plain_string_contents` PASS (nó là chốt regression).

- [ ] **Step 3: Sửa `_call`**

Thay toàn bộ method `_call` trong `services/inference/providers/gemini_provider.py`:

```python
    @staticmethod
    def _call(client, request, policy):
        json_mode = request.output_mode == "json"
        if request.media:
            # Vision call: image parts first, then the instruction text.
            contents = [
                types.Part.from_bytes(data=data, mime_type=mime)
                for mime, data in request.media
            ] + [request.user_prompt]
        else:
            contents = request.user_prompt
        return client.models.generate_content(
            model=policy.primary_model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=request.system_prompt,
                temperature=request.temperature,
                response_mime_type="application/json" if json_mode else None,
            ),
        )
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests\services\inference\test_gemini_provider.py -q`
Expected: tất cả PASS.

- [ ] **Step 5: Commit**

```powershell
git add services\inference\providers\gemini_provider.py tests\services\inference\test_gemini_provider.py
git commit -m "feat: build multimodal contents in GeminiProvider when request has media"
```

---

### Task 3: Đăng ký agent `knowledge_ocr` + `knowledge_classify`

**Files:**
- Modify: `services/inference/factory.py:9-44` (dict `agent_overrides`)
- Test: `tests/services/inference/test_factory.py` (thêm vào cuối file)

- [ ] **Step 1: Viết failing test**

Thêm vào cuối `tests/services/inference/test_factory.py`:

```python
def test_knowledge_ocr_agent_uses_default_model_with_fallback():
    gateway = build_default_gateway()
    policy = gateway.registry.resolve("knowledge_ocr")
    assert policy.primary_model == "gemini-2.5-flash-lite"   # default model (spec D1)
    assert policy.output_mode == "free_text"
    assert policy.allow_fallback is True
    assert policy.fallback_model == "gemini-2.5-flash"


def test_knowledge_classify_agent_uses_json_mode():
    gateway = build_default_gateway()
    policy = gateway.registry.resolve("knowledge_classify")
    assert policy.primary_model == "gemini-2.5-flash-lite"
    assert policy.output_mode == "json"
    assert policy.max_retries == 1
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests\services\inference\test_factory.py -q`
Expected: 2 test mới FAILED (`knowledge_ocr` chưa có override nên `allow_fallback` là `False`; `knowledge_classify` resolve về `output_mode="free_text"` mặc định).

- [ ] **Step 3: Thêm overrides vào factory**

Trong `services/inference/factory.py`, thêm 2 entry vào dict `agent_overrides` (sau entry `"synthesis_agent"`, trước dấu đóng `}`):

```python
            "knowledge_ocr": {
                "output_mode": "free_text",
                "max_retries": 1,
                "allow_fallback": True,
                "fallback_model": "gemini-2.5-flash",
            },
            "knowledge_classify": {"output_mode": "json", "max_retries": 1},
```

Lý do fallback model lớn hơn (`gemini-2.5-flash`): khi primary lỗi API cứng giữa chừng,
gateway thử model khác trước khi raise — giảm số trang `pages_ocr_failed`.

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests\services\inference\test_factory.py -q`
Expected: tất cả PASS.

- [ ] **Step 5: Chạy toàn bộ suite inference để chốt không hồi quy**

Run: `.\.venv\Scripts\python.exe -m pytest tests\services\inference -q`
Expected: tất cả PASS.

- [ ] **Step 6: Commit**

```powershell
git add services\inference\factory.py tests\services\inference\test_factory.py
git commit -m "feat: register knowledge_ocr and knowledge_classify agents in default gateway"
```

---

## Định nghĩa hoàn thành (Plan 01)

- `InferenceRequest(media=[("image/png", b"...")])` hợp lệ; không truyền `media` → `[]`.
- `GeminiProvider` gửi `contents=[Part, prompt]` khi có media, `contents=prompt` khi không.
- `gateway.registry.resolve("knowledge_ocr")` / `resolve("knowledge_classify")` trả policy như test trên.
- `.\.venv\Scripts\python.exe -m pytest tests\services\inference -q` xanh toàn bộ.
