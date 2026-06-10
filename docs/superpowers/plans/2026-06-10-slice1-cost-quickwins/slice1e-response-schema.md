# Slice 1 — Plan E: Structured-output schema for the intent router (robustness)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Priority: LOWEST in Slice 1.** This is a robustness change, not a cost win — `STRUCTURE_FAILURE` retries are rare at `temperature=0` on flash-lite. Safe to skip under time pressure. Scoped to the intent router only; `profile_extractor` is a follow-up.

**Goal:** Pass a Gemini `response_schema` for the intent classification call so the model is constrained to the `IntentResult` shape server-side, making malformed JSON (and the wasteful same-prompt retry it triggers) effectively impossible.

**Architecture:** Add an optional `response_schema` to `InferenceRequest`; `GeminiProvider._call` attaches it to `GenerateContentConfig` only for JSON calls when present. `IntentRouter` passes `IntentResult` as the schema. Default `None` ⇒ unchanged for every other call site.

**Tech Stack:** Python, pytest, `google.genai` (`response_schema` accepts a Pydantic model class).

Spec: `docs/superpowers/specs/2026-06-10-slice1-cost-quickwins-design.md` §1d.

---

### Task 1: `response_schema` on `InferenceRequest` + provider plumbing

**Files:**
- Modify: `services/inference/models.py:10-21`
- Modify: `services/inference/providers/gemini_provider.py:36-56`
- Test: `tests/services/inference/test_gemini_provider.py`

- [ ] **Step 1: Write the failing test**

```python
def test_response_schema_passed_to_config_for_json():
    import pydantic

    class _Shape(pydantic.BaseModel):
        route: str

    captured = {}
    pool = _pool({"k1": FakeClient(text='{"route": "X"}', captured=captured)})
    provider = GeminiProvider(pool=pool)
    request = InferenceRequest(
        agent_name="intent_router", task_type="t",
        system_prompt="sys", user_prompt="usr",
        output_mode="json", response_schema=_Shape,
    )
    provider.generate(request, _policy())
    assert captured["config"].response_schema is _Shape


def test_no_response_schema_leaves_config_unset():
    captured = {}
    pool = _pool({"k1": FakeClient(text='{"ok": true}', captured=captured)})
    provider = GeminiProvider(pool=pool)
    provider.generate(_request(), _policy())  # _request() sets no schema
    assert captured["config"].response_schema is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/inference/test_gemini_provider.py::test_response_schema_passed_to_config_for_json -v`
Expected: FAIL — `InferenceRequest` has no field `response_schema`.

- [ ] **Step 3: Write minimal implementation**

In `services/inference/models.py`, add the field (use `Any` — the value is a Pydantic model class, not data):

```python
class InferenceRequest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    agent_name: str
    task_type: str
    system_prompt: str
    user_prompt: str
    output_mode: str = "free_text"
    schema_name: Optional[str] = None
    response_schema: Optional[Any] = None
    temperature: float = 0.0
    media: List[Tuple[str, bytes]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
```

(Add `ConfigDict` to the existing `from pydantic import ...` line. `Any` is already imported from `typing`.)

In `services/inference/providers/gemini_provider.py`, inside `_call`, after the `thinking_config` block (or wherever `config_kwargs` is assembled), add:

```python
        if json_mode and request.response_schema is not None:
            config_kwargs["response_schema"] = request.response_schema
```

(If Plan C has not been merged yet and `_call` still builds the config inline, first refactor it to the `config_kwargs` dict form shown in Plan C, then add this block.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/inference/test_gemini_provider.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/inference/models.py services/inference/providers/gemini_provider.py tests/services/inference/test_gemini_provider.py
git commit -m "feat(inference): support response_schema on inference requests"
```

---

### Task 2: Intent router sends its `IntentResult` schema

**Files:**
- Modify: `services/chat/intent_router.py:210-219`
- Test: `tests/services/chat/test_intent_router.py`

- [ ] **Step 1: Write the failing test**

The existing tests use a fake gateway. Add one that captures the request:

```python
def test_classify_sends_response_schema():
    from services.chat.intent_router import IntentRouter, IntentResult
    from services.chat.models import ChatProfileState

    captured = {}

    class _CapturingGateway:
        def is_available(self):
            return True
        def run(self, request):
            captured["request"] = request
            from services.inference.models import InferenceResult
            return InferenceResult(
                agent_name=request.agent_name, model="m", provider="p",
                content='{"route": "ADVISORY_FLOW"}',
                parsed_data={"route": "ADVISORY_FLOW"},
            )

    router = IntentRouter(gateway=_CapturingGateway())
    router.classify("25 điểm A00 nên chọn trường nào", ChatProfileState())
    assert captured["request"].response_schema is IntentResult
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_intent_router.py::test_classify_sends_response_schema -v`
Expected: FAIL — `response_schema` is `None`.

- [ ] **Step 3: Write minimal implementation**

In `services/chat/intent_router.py`, add `response_schema=IntentResult` to the `InferenceRequest` built in `classify`:

```python
            result = self._gateway.run(
                InferenceRequest(
                    agent_name="intent_router",
                    task_type="intent_classification",
                    system_prompt=INTENT_SYSTEM_PROMPT,
                    user_prompt=self._build_user_prompt(message, profile_state, history),
                    output_mode="json",
                    response_schema=IntentResult,
                    temperature=0.0,
                )
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/chat/test_intent_router.py -q`
Expected: PASS (the prompt's JSON description stays as belt-and-suspenders; parsing path is unchanged).

- [ ] **Step 5: Regression — provider + router suites**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/inference/test_gemini_provider.py tests/services/chat/test_intent_router.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add services/chat/intent_router.py tests/services/chat/test_intent_router.py
git commit -m "feat(chat): constrain intent classification with a response schema"
```

---

## Self-review notes

- `IntentResult` has `field_validator`s (`_coerce_topic`, `_coerce_topics`) that run **after** parsing in `IntentResult.model_validate` — unchanged. The server-side schema only constrains generation, not our post-parse normalization.
- Every other call site leaves `response_schema=None` → no behavior change.
- `profile_extractor` schema is deliberately out of scope (its delta shape is a sparse dict of optional slots; a dedicated model is a separate small follow-up).
