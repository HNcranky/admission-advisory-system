# Langfuse Prompt Management — Plan 02: Generation Linking Seam

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thread a Langfuse prompt handle from an `InferenceRequest` through the gateway into `record_generation`, so every generation can be linked to the exact prompt version that produced it.

**Architecture:** Add an optional `prompt` field to `InferenceRequest` (default `None` — every existing caller is unaffected). The gateway forwards `request.prompt` to both `record_generation(...)` calls (primary + fallback paths). `record_generation` gains a `prompt=None` parameter and passes it to `start_as_current_generation(..., prompt=prompt)`. All paths no-op when `prompt is None` or Langfuse is disabled. No call site sets `prompt` yet — that happens in Plan 03.

**Tech Stack:** Python, Pydantic v2, `langfuse>=3,<4`, pytest. Depends on: nothing (independent of Plan 01). Spec: `docs/superpowers/specs/2026-06-18-langfuse-prompt-management-design.md` §3.2, §4, §5.

---

### Task 1: Add `prompt` field to `InferenceRequest`

**Files:**
- Modify: `services/inference/models.py:10-26`
- Test: `tests/services/inference/test_models_prompt_field.py`

- [ ] **Step 1: Write the failing test**

Create `tests/services/inference/test_models_prompt_field.py`:

```python
from services.inference.models import InferenceRequest


def test_prompt_defaults_to_none():
    req = InferenceRequest(
        agent_name="x", task_type="t", system_prompt="s", user_prompt="u",
    )
    assert req.prompt is None


def test_prompt_accepts_arbitrary_handle():
    sentinel = object()  # stands in for a Langfuse prompt client
    req = InferenceRequest(
        agent_name="x", task_type="t", system_prompt="s", user_prompt="u",
        prompt=sentinel,
    )
    assert req.prompt is sentinel
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/inference/test_models_prompt_field.py -v`
Expected: `test_prompt_defaults_to_none` FAILS with `AttributeError: 'InferenceRequest' object has no attribute 'prompt'`

(Use the project venv: `.venv/bin/python -m pytest ...` on Linux, `.\.venv\Scripts\python.exe -m pytest ...` on Windows.)

- [ ] **Step 3: Add the field**

In `services/inference/models.py`, inside `InferenceRequest`, add the field after `metadata` (the class already sets `model_config = ConfigDict(arbitrary_types_allowed=True)`, so an opaque handle is allowed):

```python
    # Optional Langfuse prompt client (from PromptService) used to link this
    # generation to its prompt version in Langfuse. Default None => existing
    # callers and the no-Langfuse path are unaffected.
    prompt: Optional[Any] = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/inference/test_models_prompt_field.py -v`
Expected: both PASS

- [ ] **Step 5: Commit**

```bash
git add services/inference/models.py tests/services/inference/test_models_prompt_field.py
git commit -m "feat(inference): add optional prompt handle to InferenceRequest"
```

---

### Task 2: `record_generation` forwards `prompt` to the generation

**Files:**
- Modify: `observability/run_trace.py:124-160`
- Modify: `tests/observability/test_run_trace.py` (update fake + add assertion)

- [ ] **Step 1: Update the test fake and write the failing test**

In `tests/observability/test_run_trace.py`, update `_FakeLangfuse.start_as_current_generation` to accept and record `prompt`:

```python
    def start_as_current_generation(self, *, name, model=None, input=None,
                                    model_parameters=None, metadata=None, prompt=None):
        self.recorder["generations"].append(
            {"name": name, "model": model, "input": input, "prompt": prompt}
        )
        return _FakeSpan(self.recorder, "gen:" + name)
```

Then append a new test:

```python
def test_record_generation_forwards_prompt_handle(monkeypatch):
    rec = _recorder()
    monkeypatch.setattr(rt, "get_langfuse", lambda: _FakeLangfuse(rec))

    class _Req:
        agent_name = "intent_router"
        task_type = "intent_classification"
        system_prompt = "sys"
        user_prompt = "usr"
        temperature = 0.0

    class _Res:
        model = "gemini-2.5-flash-lite"
        content = "answer"
        failure_type = None

    handle = object()
    rt.record_generation(_Req(), _Res(), prompt=handle)
    assert rec["generations"][0]["prompt"] is handle


def test_record_generation_prompt_defaults_none(monkeypatch):
    rec = _recorder()
    monkeypatch.setattr(rt, "get_langfuse", lambda: _FakeLangfuse(rec))

    class _Req:
        agent_name = "intent_router"
        task_type = "t"
        system_prompt = "sys"
        user_prompt = "usr"
        temperature = 0.0

    class _Res:
        model = "m"
        content = "a"
        failure_type = None

    rt.record_generation(_Req(), _Res())
    assert rec["generations"][0]["prompt"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/observability/test_run_trace.py -v`
Expected: the two new tests FAIL — `record_generation` has no `prompt` kwarg / `prompt` key absent.

- [ ] **Step 3: Add the `prompt` parameter and forward it**

In `observability/run_trace.py`, change the `record_generation` signature (line ~124) to add `prompt=None`:

```python
def record_generation(request, result, usage=None, latency_ms=None, attempt=None,
                      used_fallback=None, failure_type=None, model=None, prompt=None):
```

Then in the `with client.start_as_current_generation(...)` call, add `prompt=prompt` as a keyword argument:

```python
        with client.start_as_current_generation(
            name=getattr(request, "agent_name", "generation"),
            model=model or getattr(result, "model", None),
            input=_redact({
                "system": getattr(request, "system_prompt", None),
                "user": getattr(request, "user_prompt", None),
            }),
            model_parameters={"temperature": getattr(request, "temperature", None)},
            prompt=prompt,
        ) as gen:
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/observability/test_run_trace.py -v`
Expected: all PASS (existing tests still green — the fake now accepts `prompt`).

- [ ] **Step 5: Commit**

```bash
git add observability/run_trace.py tests/observability/test_run_trace.py
git commit -m "feat(observability): link prompt handle on generation"
```

---

### Task 3: Gateway forwards `request.prompt` to both record_generation calls

**Files:**
- Modify: `services/inference/gateway.py:37-41` and `:61-65`
- Test: `tests/services/inference/test_gateway_prompt_link.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/services/inference/test_gateway_prompt_link.py`:

```python
import services.inference.gateway as gw
from services.inference.gateway import LLMGateway
from services.inference.models import InferencePolicy, InferenceRequest, InferenceResult


class _OkProvider:
    def generate(self, request, policy):
        return InferenceResult(
            agent_name=request.agent_name, model=policy.primary_model,
            provider="fake", content="ok", failure_type=None,
        )


class _PrimaryFailsProvider:
    """Primary attempt structure-fails so the gateway uses the fallback model."""

    def __init__(self):
        self.calls = 0

    def generate(self, request, policy):
        self.calls += 1
        if self.calls == 1:
            return InferenceResult(
                agent_name=request.agent_name, model=policy.primary_model,
                provider="fake", content="", failure_type="STRUCTURE_FAILURE",
            )
        return InferenceResult(
            agent_name=request.agent_name, model=policy.primary_model,
            provider="fake", content="ok", failure_type=None,
        )


class _Registry:
    def __init__(self, policy):
        self._policy = policy

    def resolve(self, agent_name):
        return self._policy


def _request(prompt):
    return InferenceRequest(
        agent_name="intent_router", task_type="intent_classification",
        system_prompt="s", user_prompt="u", prompt=prompt,
    )


def test_primary_path_forwards_prompt(monkeypatch):
    captured = []
    monkeypatch.setattr(gw, "record_generation", lambda **kw: captured.append(kw))
    policy = InferencePolicy(agent_name="intent_router", primary_model="m", max_retries=0)
    gateway = LLMGateway(registry=_Registry(policy), providers={"gemini": _OkProvider()})
    sentinel = object()
    gateway.run(_request(sentinel))
    assert captured and captured[0]["prompt"] is sentinel


def test_fallback_path_forwards_prompt(monkeypatch):
    captured = []
    monkeypatch.setattr(gw, "record_generation", lambda **kw: captured.append(kw))
    policy = InferencePolicy(
        agent_name="intent_router", primary_model="m", fallback_model="m2",
        allow_fallback=True, max_retries=0,
    )
    gateway = LLMGateway(
        registry=_Registry(policy), providers={"gemini": _PrimaryFailsProvider()},
    )
    sentinel = object()
    gateway.run(_request(sentinel))
    # both the primary (structure-failure) and fallback generations carry the handle
    assert all(kw["prompt"] is sentinel for kw in captured)
    assert len(captured) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/services/inference/test_gateway_prompt_link.py -v`
Expected: FAIL — `KeyError: 'prompt'` (gateway does not pass `prompt` to `record_generation` yet).

- [ ] **Step 3: Add `prompt=request.prompt` to both calls**

In `services/inference/gateway.py`, the **primary** `record_generation(...)` (line ~37) becomes:

```python
            record_generation(
                request=request, result=result, usage=result.usage, latency_ms=latency_ms,
                attempt=attempt, used_fallback=False, model=policy.primary_model,
                failure_type=result.failure_type, prompt=request.prompt,
            )
```

And the **fallback** `record_generation(...)` (line ~61) becomes:

```python
            record_generation(
                request=request, result=result, usage=result.usage, latency_ms=latency_ms,
                attempt=policy.max_retries + 1, used_fallback=True,
                model=fallback_policy.primary_model, failure_type=result.failure_type,
                prompt=request.prompt,
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/services/inference/test_gateway_prompt_link.py -v`
Expected: both PASS

- [ ] **Step 5: Run the inference + observability suites for regressions**

Run: `python -m pytest tests/services/inference tests/observability -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add services/inference/gateway.py tests/services/inference/test_gateway_prompt_link.py
git commit -m "feat(gateway): forward prompt handle to record_generation"
```

---

## Self-Review

- **Spec coverage:** §3.2 — `InferenceRequest.prompt` (Task 1), `record_generation(prompt=...)` (Task 2), gateway forwarding on both paths (Task 3). §5 — generation-linking tests in all three tasks.
- **Placeholders:** none.
- **Type consistency:** `prompt`/`request.prompt` opaque handle threaded consistently; `record_generation(..., prompt=...)` keyword matches between Task 2 (definition) and Task 3 (call sites). `InferencePolicy(max_retries=0)` makes the primary loop run exactly once.
- **Note:** This plan never sets a non-None `prompt`; it only proves the wire is connected. Plan 03 makes call sites pass `cp.handle`.
