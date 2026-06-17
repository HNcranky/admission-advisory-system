# Langfuse Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stream every advisory run to a self-hosted Langfuse instance — one trace per run, a span per pipeline stage, a generation per Gemini call with token usage — without touching the existing Postgres debug-panel tracer.

**Architecture:** A new leaf package `observability/` holds a lazily-built Langfuse singleton plus thin, error-swallowing helpers. Three existing chokepoints get one edit each (`RunDispatcher.execute` → root trace, the `traced` decorator → stage span, `LLMGateway.run` → generation), and the Gemini provider is refactored to surface `usage_metadata`. Nesting is automatic because the whole pipeline runs synchronously on one worker thread (OTEL contextvars).

**Tech Stack:** Python 3.12, Langfuse Python SDK v3 (OTEL-based), `google-genai`, FastAPI, LangGraph, pytest, Docker Compose.

Design spec: `docs/superpowers/specs/2026-06-17-langfuse-observability-design.md`.

## Global Constraints

- **Never run `git push`.** Commit only.
- **No `Co-Authored-By` trailer and no Claude/AI attribution** in any commit message.
- **No `.venv` in this repo** — use system `python` (3.12). All commands below use `python -m pytest ...`.
- **Pydantic is v2** (`ConfigDict`, not `class Config`).
- **Degrade gracefully, default OFF.** `ADVISORY_LANGFUSE_ENABLED` defaults to `false`; with it off, every helper is a no-op. Any Langfuse error must be caught, `logger.warning`-ed, and swallowed — a Langfuse fault must never break or fail an advisory run.
- **Tests run with Langfuse disabled** (no network). The test DB is auto-isolated to `admission_test`; do not touch dev data.
- **Capture raw** (no redaction in phase 1); a no-op `_redact` seam exists for later.
- **Secrets** (`LANGFUSE_SECRET_KEY`, Langfuse stack secrets) live only in gitignored env files — never commit them.

---

### Task 1: Langfuse client singleton (`observability/langfuse_client.py`)

Adds the dependency, env config, and the null-safe client factory every later task depends on.

**Files:**
- Modify: `requirements.txt`
- Modify: `.env.example`
- Create: `observability/__init__.py`
- Create: `observability/langfuse_client.py`
- Create: `tests/observability/__init__.py`
- Create: `tests/observability/test_langfuse_client.py`

**Interfaces:**
- Produces:
  - `get_langfuse() -> "Langfuse | None"` — process-wide singleton; `None` when disabled or misconfigured.
  - `flush_langfuse() -> None` — flush batched events; no-op when disabled; never raises.
  - `reset_langfuse_client() -> None` — test hook clearing the cache.

- [ ] **Step 1: Install the dependency and pin it**

Run:
```bash
python -m pip install "langfuse>=3,<4"
```
Add this line to `requirements.txt` (keep the file's existing ordering/grouping; place near other service SDKs):
```
langfuse>=3,<4
```

- [ ] **Step 2: Add env vars to `.env.example`**

Append:
```
# --- Observability (Langfuse) ---
# Master switch. When false (default) all Langfuse instrumentation is a no-op.
ADVISORY_LANGFUSE_ENABLED=false
LANGFUSE_HOST=http://localhost:3000
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
```

- [ ] **Step 3: Write the failing tests**

Create `tests/observability/__init__.py` (empty file).

Create `tests/observability/test_langfuse_client.py`:
```python
import observability.langfuse_client as lc


def _reset():
    lc.reset_langfuse_client()


def test_disabled_returns_none(monkeypatch):
    monkeypatch.setenv("ADVISORY_LANGFUSE_ENABLED", "false")
    _reset()
    assert lc.get_langfuse() is None


def test_enabled_but_missing_keys_returns_none_and_warns(monkeypatch, caplog):
    import logging
    monkeypatch.setenv("ADVISORY_LANGFUSE_ENABLED", "true")
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    _reset()
    with caplog.at_level(logging.WARNING, logger="observability.langfuse_client"):
        assert lc.get_langfuse() is None
    assert any("LANGFUSE_PUBLIC_KEY" in r.message for r in caplog.records)


def test_enabled_with_keys_builds_client_once(monkeypatch):
    monkeypatch.setenv("ADVISORY_LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setenv("LANGFUSE_HOST", "http://localhost:3000")
    _reset()

    built = []

    class _FakeLangfuse:
        def __init__(self, **kwargs):
            built.append(kwargs)

    import langfuse
    monkeypatch.setattr(langfuse, "Langfuse", _FakeLangfuse)

    first = lc.get_langfuse()
    second = lc.get_langfuse()
    assert first is second is not None
    assert len(built) == 1
    assert built[0]["public_key"] == "pk"
    assert built[0]["secret_key"] == "sk"
    assert built[0]["host"] == "http://localhost:3000"


def test_flush_is_noop_when_disabled(monkeypatch):
    monkeypatch.setenv("ADVISORY_LANGFUSE_ENABLED", "false")
    _reset()
    lc.flush_langfuse()  # must not raise
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `python -m pytest tests/observability/test_langfuse_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'observability'`.

- [ ] **Step 5: Implement the module**

Create `observability/__init__.py` (empty file).

Create `observability/langfuse_client.py`:
```python
import logging
import os
import threading

logger = logging.getLogger(__name__)

_client = None
_initialized = False
_lock = threading.Lock()

_TRUTHY = {"1", "true", "yes", "on"}


def _enabled() -> bool:
    return os.getenv("ADVISORY_LANGFUSE_ENABLED", "false").strip().lower() in _TRUTHY


def get_langfuse():
    """Return a process-wide Langfuse client, or None when disabled/misconfigured.

    None => every observability helper no-ops. Mirrors build_default_gateway()'s
    graceful-degradation contract: callers never need to special-case Langfuse.
    """
    global _client, _initialized
    if _initialized:
        return _client
    with _lock:
        if _initialized:
            return _client
        _initialized = True
        if not _enabled():
            _client = None
            return _client
        public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
        secret_key = os.getenv("LANGFUSE_SECRET_KEY")
        host = os.getenv("LANGFUSE_HOST", "http://localhost:3000")
        if not public_key or not secret_key:
            logger.warning(
                "ADVISORY_LANGFUSE_ENABLED is set but LANGFUSE_PUBLIC_KEY/"
                "LANGFUSE_SECRET_KEY are missing; observability disabled"
            )
            _client = None
            return _client
        try:
            from langfuse import Langfuse
            _client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
        except Exception as exc:  # SDK import or init failure must not break the app
            logger.warning("Langfuse client init failed; observability disabled: %r", exc)
            _client = None
        return _client


def flush_langfuse() -> None:
    client = get_langfuse()
    if client is None:
        return
    try:
        client.flush()
    except Exception as exc:
        logger.warning("Langfuse flush failed: %r", exc)


def reset_langfuse_client() -> None:
    """Test hook: clear the cached client so env changes take effect."""
    global _client, _initialized
    with _lock:
        _client = None
        _initialized = False
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/observability/test_langfuse_client.py -v`
Expected: PASS (4 passed).

- [ ] **Step 7: Commit**

```bash
git add requirements.txt .env.example observability/__init__.py observability/langfuse_client.py tests/observability/__init__.py tests/observability/test_langfuse_client.py
git commit -m "feat(observability): add null-safe Langfuse client singleton"
```

---

### Task 2: Surface Gemini token usage on `InferenceResult`

Pure data plumbing — independent of Langfuse, valuable on its own. Stops discarding `usage_metadata`.

**Files:**
- Modify: `services/inference/models.py`
- Modify: `services/inference/providers/gemini_provider.py`
- Create: `tests/services/inference/test_gemini_provider_usage.py`

**Interfaces:**
- Produces: `InferenceResult.usage: Optional[Dict[str, int]]` — `{"input": int|None, "output": int|None, "total": int|None}` or `None` when the response has no `usage_metadata`.

- [ ] **Step 1: Write the failing tests**

Create `tests/services/inference/test_gemini_provider_usage.py`:
```python
from types import SimpleNamespace

from services.inference.models import InferencePolicy, InferenceRequest
from services.inference.providers.gemini_provider import GeminiProvider
from services.inference.providers.key_pool import GeminiKeyPool


def _request():
    return InferenceRequest(
        agent_name="reasoning_agent", task_type="t",
        system_prompt="sys", user_prompt="usr", output_mode="json",
    )


def _policy():
    return InferencePolicy(agent_name="reasoning_agent", primary_model="gemini-2.5-flash-lite")


def _provider(response):
    class _Models:
        def generate_content(self, **kwargs):
            return response

    class _Client:
        models = _Models()

    pool = GeminiKeyPool(["k"], client_factory=lambda k: _Client())
    return GeminiProvider(pool=pool)


def test_usage_metadata_is_surfaced_into_result():
    response = SimpleNamespace(
        text='{"ok": true}',
        usage_metadata=SimpleNamespace(
            prompt_token_count=10, candidates_token_count=5, total_token_count=15
        ),
    )
    result = _provider(response).generate(_request(), _policy())
    assert result.usage == {"input": 10, "output": 5, "total": 15}


def test_missing_usage_metadata_yields_none():
    response = SimpleNamespace(text='{"ok": true}')  # no usage_metadata attr
    result = _provider(response).generate(_request(), _policy())
    assert result.usage is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/services/inference/test_gemini_provider_usage.py -v`
Expected: FAIL — `InferenceResult` has no field `usage` / `result.usage` raises `AttributeError`.

- [ ] **Step 3: Add the `usage` field to `InferenceResult`**

In `services/inference/models.py`, inside `class InferenceResult`, add the field after `failure_type`:
```python
    failure_type: Optional[str] = None
    usage: Optional[Dict[str, int]] = None
```
(`Dict` and `Optional` are already imported at the top of the file.)

- [ ] **Step 4: Capture usage in the provider**

In `services/inference/providers/gemini_provider.py`, replace the `_build_result` method (currently lines 67–87) with:
```python
    def _build_result(self, response, request, policy):
        text = (getattr(response, "text", "") or "").strip()
        usage = self._extract_usage(response)

        def _result(**kwargs):
            return InferenceResult(
                agent_name=request.agent_name,
                model=policy.primary_model,
                provider=self.provider_name,
                content=text,
                usage=usage,
                **kwargs,
            )

        if request.output_mode != "json":
            return _result()
        if not text:
            return _result(failure_type="STRUCTURE_FAILURE")
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return _result(failure_type="STRUCTURE_FAILURE")
        return _result(parsed_data=parsed)

    @staticmethod
    def _extract_usage(response):
        meta = getattr(response, "usage_metadata", None)
        if meta is None:
            return None

        def _count(name):
            value = getattr(meta, name, None)
            return int(value) if isinstance(value, (int, float)) else None

        return {
            "input": _count("prompt_token_count"),
            "output": _count("candidates_token_count"),
            "total": _count("total_token_count"),
        }
```

- [ ] **Step 5: Run the new tests plus the existing provider suite**

Run: `python -m pytest tests/services/inference/test_gemini_provider_usage.py tests/services/inference/test_gemini_provider.py -v`
Expected: PASS (new 2 passed; existing provider tests still green — `usage` is additive/optional).

- [ ] **Step 6: Commit**

```bash
git add services/inference/models.py services/inference/providers/gemini_provider.py tests/services/inference/test_gemini_provider_usage.py
git commit -m "feat(inference): surface Gemini token usage on InferenceResult"
```

---

### Task 3: Observability helpers (`observability/run_trace.py`)

The three error-swallowing helpers the chokepoints call. Depends on Task 1.

**Files:**
- Create: `observability/run_trace.py`
- Create: `tests/observability/test_run_trace.py`

**Interfaces:**
- Consumes: `observability.langfuse_client.get_langfuse`.
- Produces:
  - `advisory_run_trace(run_id, session_token, user_message, intent=None, admission_year=None)` — context manager; root span/trace; sets `session_id=session_token` and a deterministic trace id seeded from `run_id`; yields the span or `None`.
  - `stage_span(stage, sequence)` — context manager; child span named `stage`; yields the span or `None`.
  - `set_span_output(span, output_json)` — attach output to a span; no-op when `span is None`.
  - `record_generation(request, result, usage=None, latency_ms=None, attempt=None, used_fallback=None, failure_type=None, model=None)` — emit one generation observation under the active span.
  - `_redact(payload)` — phase-1 passthrough seam.

- [ ] **Step 1: Write the failing tests**

Create `tests/observability/test_run_trace.py`:
```python
import observability.run_trace as rt


class _FakeSpan:
    def __init__(self, recorder, name):
        self.recorder = recorder
        self.name = name

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.recorder["closed"].append(self.name)
        return False

    def update(self, **kwargs):
        self.recorder["updates"].append((self.name, kwargs))

    def update_trace(self, **kwargs):
        self.recorder["trace"].append(kwargs)


class _FakeLangfuse:
    def __init__(self, recorder):
        self.recorder = recorder

    def create_trace_id(self, *, seed=None):
        return "trace-" + str(seed)

    def start_as_current_span(self, *, name, input=None, trace_context=None, metadata=None):
        self.recorder["spans"].append(
            {"name": name, "input": input, "trace_context": trace_context}
        )
        return _FakeSpan(self.recorder, name)

    def start_as_current_generation(self, *, name, model=None, input=None,
                                    model_parameters=None, metadata=None):
        self.recorder["generations"].append({"name": name, "model": model, "input": input})
        return _FakeSpan(self.recorder, "gen:" + name)


def _recorder():
    return {"spans": [], "generations": [], "updates": [], "trace": [], "closed": []}


def test_helpers_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(rt, "get_langfuse", lambda: None)
    with rt.advisory_run_trace(1, "sess", "hi") as span:
        assert span is None
        with rt.stage_span("profile", 0) as s:
            assert s is None
            rt.set_span_output(s, {"x": 1})  # must not raise
    rt.record_generation(object(), object())  # must not raise


def test_advisory_run_trace_sets_session_and_trace_id(monkeypatch):
    rec = _recorder()
    monkeypatch.setattr(rt, "get_langfuse", lambda: _FakeLangfuse(rec))
    with rt.advisory_run_trace(7, "sess-abc", "em duoc 27 diem", intent="advisory"):
        pass
    assert rec["spans"][0]["name"] == "advisory-run"
    assert rec["spans"][0]["trace_context"] == {"trace_id": "trace-7"}
    assert rec["trace"][0]["session_id"] == "sess-abc"
    assert "advisory-run" in rec["closed"]


def test_stage_span_emits_named_span_and_output(monkeypatch):
    rec = _recorder()
    monkeypatch.setattr(rt, "get_langfuse", lambda: _FakeLangfuse(rec))
    with rt.stage_span("reason", 3) as span:
        rt.set_span_output(span, {"count": 2})
    assert rec["spans"][0]["name"] == "reason"
    assert ("reason", {"output": {"count": 2}}) in rec["updates"]


def test_record_generation_includes_usage_and_metadata(monkeypatch):
    rec = _recorder()
    monkeypatch.setattr(rt, "get_langfuse", lambda: _FakeLangfuse(rec))

    class _Req:
        agent_name = "reasoning_agent"
        task_type = "reason"
        system_prompt = "sys"
        user_prompt = "usr"
        temperature = 0.0

    class _Res:
        model = "gemini-2.5-flash-lite"
        content = "answer"
        failure_type = None

    rt.record_generation(
        _Req(), _Res(), usage={"input": 10, "output": 5, "total": 15},
        latency_ms=12.5, attempt=0, used_fallback=False,
    )
    assert rec["generations"][0]["name"] == "reasoning_agent"
    assert rec["generations"][0]["model"] == "gemini-2.5-flash-lite"
    gen_update = [u for u in rec["updates"] if u[0] == "gen:reasoning_agent"]
    assert gen_update, "generation should be updated with output/usage"
    payload = gen_update[0][1]
    assert payload["usage_details"] == {"input": 10, "output": 5, "total": 15}
    assert payload["output"] == "answer"


def test_errors_are_swallowed(monkeypatch):
    class _Boom:
        def create_trace_id(self, *, seed=None):
            raise RuntimeError("langfuse down")

        def start_as_current_span(self, **kwargs):
            raise RuntimeError("langfuse down")

        def start_as_current_generation(self, **kwargs):
            raise RuntimeError("langfuse down")

    monkeypatch.setattr(rt, "get_langfuse", lambda: _Boom())
    # None of these may raise:
    with rt.advisory_run_trace(1, "s", "hi") as span:
        assert span is None
        with rt.stage_span("profile", 0) as s:
            assert s is None
    rt.record_generation(object(), object())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/observability/test_run_trace.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'observability.run_trace'`.

- [ ] **Step 3: Implement the helpers**

Create `observability/run_trace.py`:
```python
import contextlib
import logging

from observability.langfuse_client import get_langfuse

logger = logging.getLogger(__name__)


def _redact(payload):
    """Phase-1 passthrough. Single seam to add masking later without
    restructuring call sites (e.g. when switching to Langfuse Cloud)."""
    return payload


def _safe_exit(cm):
    if cm is None:
        return
    try:
        cm.__exit__(None, None, None)
    except Exception as exc:
        logger.warning("langfuse span close failed: %r", exc)


@contextlib.contextmanager
def advisory_run_trace(run_id, session_token, user_message, intent=None, admission_year=None):
    """Root span/trace for one advisory run. Yields the span (or None when
    disabled). Any Langfuse error is swallowed; the run always proceeds."""
    client = get_langfuse()
    cm = None
    span = None
    if client is not None:
        try:
            trace_id = client.create_trace_id(seed=str(run_id))
            cm = client.start_as_current_span(
                name="advisory-run",
                input=_redact({"user_message": user_message, "intent": intent}),
                trace_context={"trace_id": trace_id},
            )
            span = cm.__enter__()
            span.update_trace(
                session_id=str(session_token),
                metadata={"run_id": run_id, "intent": intent, "admission_year": admission_year},
                tags=["advisory"],
            )
        except Exception as exc:
            logger.warning("langfuse advisory_run_trace open failed: %r", exc)
            _safe_exit(cm)
            cm = None
            span = None
    try:
        yield span
    finally:
        _safe_exit(cm)


@contextlib.contextmanager
def stage_span(stage, sequence):
    """Child span for one pipeline stage. Generations created while this span
    is active nest under it (OTEL contextvars, same worker thread)."""
    client = get_langfuse()
    cm = None
    span = None
    if client is not None:
        try:
            cm = client.start_as_current_span(name=stage, metadata={"sequence": sequence})
            span = cm.__enter__()
        except Exception as exc:
            logger.warning("langfuse stage_span open failed for %s: %r", stage, exc)
            _safe_exit(cm)
            cm = None
            span = None
    try:
        yield span
    finally:
        _safe_exit(cm)


def set_span_output(span, output_json):
    if span is None:
        return
    try:
        span.update(output=_redact(output_json))
    except Exception as exc:
        logger.warning("langfuse set_span_output failed: %r", exc)


def record_generation(request, result, usage=None, latency_ms=None, attempt=None,
                      used_fallback=None, failure_type=None, model=None):
    """Emit one generation observation under the active span. Each retry/fallback
    call site emits its own generation."""
    client = get_langfuse()
    if client is None:
        return
    try:
        usage_details = None
        if usage:
            usage_details = {
                "input": usage.get("input"),
                "output": usage.get("output"),
                "total": usage.get("total"),
            }
        with client.start_as_current_generation(
            name=getattr(request, "agent_name", "generation"),
            model=model or getattr(result, "model", None),
            input=_redact({
                "system": getattr(request, "system_prompt", None),
                "user": getattr(request, "user_prompt", None),
            }),
            model_parameters={"temperature": getattr(request, "temperature", None)},
        ) as gen:
            gen.update(
                output=_redact(getattr(result, "content", None)),
                usage_details=usage_details,
                metadata={
                    "attempt": attempt,
                    "used_fallback": used_fallback,
                    "failure_type": failure_type
                    if failure_type is not None
                    else getattr(result, "failure_type", None),
                    "task_type": getattr(request, "task_type", None),
                    "latency_ms": latency_ms,
                },
            )
    except Exception as exc:
        logger.warning("langfuse record_generation failed: %r", exc)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/observability/test_run_trace.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Verify the SDK method names exist on the installed client**

Run:
```bash
python -c "from langfuse import Langfuse; print(all(hasattr(Langfuse, n) for n in ['start_as_current_span','start_as_current_generation','create_trace_id']))"
```
Expected: `True`. If `False`, the installed Langfuse major version differs from v3 — stop and reconcile the method names in `run_trace.py` before proceeding (do not invent names).

- [ ] **Step 6: Commit**

```bash
git add observability/run_trace.py tests/observability/test_run_trace.py
git commit -m "feat(observability): add run-trace span/generation helpers"
```

---

### Task 4: Wire stage spans into the `traced` decorator

One edit covers all six pipeline nodes; no `graph.py` change. Depends on Task 3.

**Files:**
- Modify: `services/tracing/agent_tracer.py`
- Create: `tests/services/tracing/test_agent_tracer_langfuse.py`

**Interfaces:**
- Consumes: `observability.run_trace.stage_span`, `observability.run_trace.set_span_output`.

- [ ] **Step 1: Write the failing test**

Create `tests/services/tracing/test_agent_tracer_langfuse.py`:
```python
import observability.run_trace as rt
from state import AgentState
from services.tracing.agent_tracer import traced


class _Repo:
    def start_event(self, run_id, stage, sequence):
        return 1

    def complete_event(self, event_id, output_json):
        return None

    def fail_event(self, event_id, error_text):
        return None


class _FakeSpan:
    def __init__(self, rec, name):
        self.rec, self.name = rec, name

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def update(self, **kwargs):
        self.rec["updates"].append((self.name, kwargs))


class _FakeLangfuse:
    def __init__(self, rec):
        self.rec = rec

    def start_as_current_span(self, *, name, metadata=None, **kwargs):
        self.rec["spans"].append(name)
        return _FakeSpan(self.rec, name)


def test_traced_opens_langfuse_stage_span_and_sets_output(monkeypatch):
    rec = {"spans": [], "updates": []}
    monkeypatch.setattr(rt, "get_langfuse", lambda: _FakeLangfuse(rec))

    def agent(state):
        state.user_query = "done"
        return state

    extractor = lambda result, state: {"snapshot": result.user_query}
    wrapped = traced("profile", 0, extractor, repository=_Repo())(agent)
    wrapped(AgentState(user_query="start", trace_run_id=7))

    assert rec["spans"] == ["profile"]
    assert ("profile", {"output": {"snapshot": "done"}}) in rec["updates"]


def test_langfuse_failure_does_not_break_agent(monkeypatch):
    class _Boom:
        def start_as_current_span(self, **kwargs):
            raise RuntimeError("langfuse down")

    monkeypatch.setattr(rt, "get_langfuse", lambda: _Boom())

    def agent(state):
        state.user_query = "ran-anyway"
        return state

    wrapped = traced("reason", 3, lambda r, s: {}, repository=_Repo())(agent)
    result = wrapped(AgentState(user_query="x", trace_run_id=1))
    assert result.user_query == "ran-anyway"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/services/tracing/test_agent_tracer_langfuse.py -v`
Expected: FAIL — no Langfuse span opened (`rec["spans"]` empty).

- [ ] **Step 3: Implement the wiring**

In `services/tracing/agent_tracer.py`, add the import near the top (after the existing `from services.tracing.trace_repository import TraceRepository`):
```python
from observability.run_trace import stage_span, set_span_output
```
Replace the `wrapped` function body (currently lines 25–43) with:
```python
        def wrapped(state):
            run_id = getattr(state, "trace_run_id", None)
            if run_id is None:
                return agent_fn(state)
            event_id = _safe(repo.start_event, run_id, stage, sequence)
            with stage_span(stage, sequence) as span:
                try:
                    result = agent_fn(state)
                except Exception as exc:
                    if event_id is not None:
                        _safe(repo.fail_event, event_id, repr(exc))
                    raise
                try:
                    output_json = output_extractor(result, state)
                except Exception as exc:
                    logger.warning("trace extractor failed for stage=%s: %r", stage, exc)
                    output_json = {"_extractor_error": repr(exc)}
                set_span_output(span, output_json)
            if event_id is not None:
                _safe(repo.complete_event, event_id, output_json)
            return result
```

- [ ] **Step 4: Run the new test plus the existing tracer suite**

Run: `python -m pytest tests/services/tracing/test_agent_tracer_langfuse.py tests/services/tracing/test_agent_tracer.py -v`
Expected: PASS (new 2 passed; existing tracer tests still green — `stage_span` no-ops when Langfuse disabled).

- [ ] **Step 5: Commit**

```bash
git add services/tracing/agent_tracer.py tests/services/tracing/test_agent_tracer_langfuse.py
git commit -m "feat(observability): emit Langfuse stage span per pipeline node"
```

---

### Task 5: Emit a generation per LLM call in `LLMGateway.run`

Times each `provider.generate` and records a generation (retries + fallback included). Depends on Tasks 2 and 3.

**Files:**
- Modify: `services/inference/gateway.py`
- Create: `tests/services/inference/test_gateway_langfuse.py`

**Interfaces:**
- Consumes: `observability.run_trace.record_generation`, `InferenceResult.usage` (Task 2).

- [ ] **Step 1: Write the failing test**

Create `tests/services/inference/test_gateway_langfuse.py`:
```python
from services.inference import gateway as gw
from services.inference.gateway import LLMGateway
from services.inference.models import InferenceRequest, InferenceResult
from services.inference.registry import ModelRegistry
from services.inference.telemetry import InferenceTelemetry


class _FlakyProvider:
    """First call STRUCTURE_FAILURE, second succeeds."""

    def __init__(self):
        self.calls = 0

    def is_available(self):
        return True

    def generate(self, request, policy):
        self.calls += 1
        failure = "STRUCTURE_FAILURE" if self.calls == 1 else None
        return InferenceResult(
            agent_name=request.agent_name, model=policy.primary_model, provider="fake",
            content="{}", parsed_data={} if failure is None else None, failure_type=failure,
            usage={"input": 1, "output": 2, "total": 3},
        )


def _gateway(provider, telemetry):
    registry = ModelRegistry(
        default_model="m",
        agent_overrides={"profile_agent": {"output_mode": "json", "max_retries": 1}},
    )
    return LLMGateway(registry=registry, providers={"gemini": provider}, telemetry=telemetry)


def _request():
    return InferenceRequest(
        agent_name="profile_agent", task_type="profile_extraction",
        system_prompt="s", user_prompt="u", output_mode="json",
    )


def test_gateway_emits_one_generation_per_attempt(monkeypatch):
    calls = []
    monkeypatch.setattr(gw, "record_generation", lambda **kw: calls.append(kw))

    _gateway(_FlakyProvider(), InferenceTelemetry()).run(_request())

    assert [c["attempt"] for c in calls] == [0, 1]
    assert all(c["used_fallback"] is False for c in calls)
    assert all(c["usage"] == {"input": 1, "output": 2, "total": 3} for c in calls)
    assert all(isinstance(c["latency_ms"], (int, float)) for c in calls)
    assert calls[-1]["model"] == "m"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/services/inference/test_gateway_langfuse.py -v`
Expected: FAIL — `module 'services.inference.gateway' has no attribute 'record_generation'`.

- [ ] **Step 3: Implement the wiring**

In `services/inference/gateway.py`, replace the import block (lines 1–2) with:
```python
import time

from observability.run_trace import record_generation
from services.inference.models import InferenceError
from services.inference.providers.gemini_provider import GeminiProvider
```
Replace the `run` method's primary-attempt loop and fallback block (lines 16–55) with:
```python
    def run(self, request):
        policy = self.registry.resolve(request.agent_name)
        provider = self.providers["gemini"]

        result = None
        primary_error = None
        for attempt in range(policy.max_retries + 1):
            start = time.perf_counter()
            try:
                result = provider.generate(request, policy)
            except InferenceError as exc:
                # Hard API failure (network, auth, rate limit, 5xx). Retrying the
                # same model rarely helps, so stop and let fallback try instead.
                primary_error = exc
                self._record(request, policy.primary_model, attempt, "API_ERROR", used_fallback=False)
                break
            latency_ms = (time.perf_counter() - start) * 1000.0
            self._record(request, policy.primary_model, attempt, result.failure_type, used_fallback=False)
            record_generation(
                request=request, result=result, usage=result.usage, latency_ms=latency_ms,
                attempt=attempt, used_fallback=False, model=policy.primary_model,
                failure_type=result.failure_type,
            )
            if result.failure_type != "STRUCTURE_FAILURE":
                return result

        if policy.allow_fallback and policy.fallback_model:
            fallback_policy = policy.model_copy(update={"primary_model": policy.fallback_model})
            start = time.perf_counter()
            try:
                result = provider.generate(request, fallback_policy)
            except InferenceError as exc:
                self._record(
                    request, fallback_policy.primary_model, policy.max_retries + 1,
                    "API_ERROR", used_fallback=True,
                )
                raise
            latency_ms = (time.perf_counter() - start) * 1000.0
            self._record(
                request, fallback_policy.primary_model, policy.max_retries + 1,
                result.failure_type, used_fallback=True,
            )
            record_generation(
                request=request, result=result, usage=result.usage, latency_ms=latency_ms,
                attempt=policy.max_retries + 1, used_fallback=True,
                model=fallback_policy.primary_model, failure_type=result.failure_type,
            )
            return result

        # No fallback configured: surface the hard error so the call site can
        # degrade gracefully (every gateway.run() call site guards InferenceError).
        if primary_error is not None:
            raise primary_error
        return result
```

- [ ] **Step 4: Run the new test plus the existing gateway suites**

Run: `python -m pytest tests/services/inference/test_gateway_langfuse.py tests/services/inference/test_gateway.py tests/services/inference/test_gateway_retry_and_fallback.py tests/services/inference/test_gateway_telemetry.py -v`
Expected: PASS (new 1 passed; existing gateway behaviour unchanged — `record_generation` no-ops when Langfuse disabled).

- [ ] **Step 5: Commit**

```bash
git add services/inference/gateway.py tests/services/inference/test_gateway_langfuse.py
git commit -m "feat(observability): record a Langfuse generation per LLM attempt"
```

---

### Task 6: Open the root trace in `RunDispatcher.execute`

The only spot with `run_id` + `session_token` + message. Wraps the runner so stage spans nest. Depends on Task 3.

**Files:**
- Modify: `services/chat/run_dispatcher.py`
- Create: `tests/services/chat/test_run_dispatcher_langfuse.py`

**Interfaces:**
- Consumes: `observability.run_trace.advisory_run_trace`.

- [ ] **Step 1: Write the failing test**

Create `tests/services/chat/test_run_dispatcher_langfuse.py`:
```python
import contextlib

from services.chat import run_dispatcher as rd
from services.chat.models import ChatProfileState
from services.chat.run_dispatcher import RunDispatcher


class FakeRepository:
    def __init__(self):
        self.completed = None
        self.messages = []

    def mark_run_running(self, run_id):
        pass

    def complete_run(self, run_id, result_json, final_answer):
        self.completed = (run_id, result_json, final_answer)

    def append_message(self, session_token, role, content, kind="chat"):
        self.messages.append((session_token, role, kind, content))

    def update_session_status(self, session_token, status):
        pass


def test_execute_opens_advisory_run_trace(monkeypatch):
    captured = {}

    @contextlib.contextmanager
    def fake_trace(run_id, session_token, user_message, intent=None, admission_year=None):
        captured["args"] = (run_id, session_token, user_message)
        yield None

    monkeypatch.setattr(rd, "advisory_run_trace", fake_trace)

    repo = FakeRepository()
    dispatcher = RunDispatcher(
        repository=repo,
        runner=lambda profile_state, latest_user_message, trace_run_id=None,
        correction_note=None, closing_seed=None: {"final_answer": "ok"},
    )
    dispatcher.execute(
        session_token="sess-1", run_id=42, latest_user_message="hi",
        profile_state=ChatProfileState(admission_year=2026),
    )

    assert captured["args"] == (42, "sess-1", "hi")
    assert repo.completed[0] == 42
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/services/chat/test_run_dispatcher_langfuse.py -v`
Expected: FAIL — `module 'services.chat.run_dispatcher' has no attribute 'advisory_run_trace'`.

- [ ] **Step 3: Implement the wiring**

In `services/chat/run_dispatcher.py`, add the import after the existing `from services.chat.base_dispatcher import BaseRunDispatcher`:
```python
from observability.run_trace import advisory_run_trace
```
Replace the `execute` method body (lines 14–27) with:
```python
    def execute(self, session_token: str, run_id: int, latest_user_message: str, profile_state,
                correction_note: dict | None = None, closing_seed: int = 0):
        try:
            self.repository.mark_run_running(run_id)
            with advisory_run_trace(
                run_id, session_token, latest_user_message,
                intent=getattr(profile_state, "intent", None),
                admission_year=getattr(profile_state, "admission_year", None),
            ):
                result = self.runner(profile_state, latest_user_message, trace_run_id=run_id,
                                     correction_note=correction_note, closing_seed=closing_seed)
            final_answer = result.get("final_answer") or result.get("advisory") or ""
            self.repository.complete_run(run_id, result, final_answer)
            self.repository.append_message(session_token, "assistant", final_answer, "assistant_result")
            self.repository.update_session_status(session_token, "completed")
        except Exception:
            logger.exception("advisory run %s failed for session %s", run_id, session_token)
            self._mark_failed(session_token)
            raise
```

- [ ] **Step 4: Run the new test plus the existing dispatcher suite**

Run: `python -m pytest tests/services/chat/test_run_dispatcher_langfuse.py tests/services/chat/test_run_dispatcher.py -v`
Expected: PASS (new 1 passed; existing dispatcher tests still green).

- [ ] **Step 5: Commit**

```bash
git add services/chat/run_dispatcher.py tests/services/chat/test_run_dispatcher_langfuse.py
git commit -m "feat(observability): open Langfuse root trace per advisory run"
```

---

### Task 7: Flush batched events on app shutdown

Ensures the background SDK queue is drained when the web app stops. Depends on Task 1.

**Files:**
- Modify: `web/app.py`
- Create: `tests/web/test_app_langfuse_flush.py`

**Interfaces:**
- Consumes: `observability.langfuse_client.flush_langfuse`.

- [ ] **Step 1: Write the failing test**

Create `tests/web/test_app_langfuse_flush.py` (create `tests/web/__init__.py` first if it does not exist):
```python
import observability.langfuse_client as lc
from web.app import build_app


def test_app_flushes_langfuse_on_shutdown(monkeypatch):
    called = []
    monkeypatch.setattr(lc, "flush_langfuse", lambda: called.append(True))

    app = build_app()
    for handler in app.router.on_shutdown:
        handler()

    assert called == [True]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/web/test_app_langfuse_flush.py -v`
Expected: FAIL — no shutdown handler calls `flush_langfuse` (`called` stays empty).

- [ ] **Step 3: Implement the shutdown hook**

In `web/app.py`, add this handler inside `build_app` immediately before `return app`:
```python
    @app.on_event("shutdown")
    def _flush_langfuse():
        try:
            from observability.langfuse_client import flush_langfuse
            flush_langfuse()
        except Exception:
            logger.exception("langfuse flush skipped")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/web/test_app_langfuse_flush.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add web/app.py tests/web/test_app_langfuse_flush.py
git commit -m "feat(observability): flush Langfuse on web app shutdown"
```

---

### Task 8: Self-hosted Langfuse Docker stack + docs

Stands up Langfuse v3 locally so traces are actually viewable. Independent of the code tasks — can be done at any point, but is required to see output end-to-end.

**Files:**
- Create: `docker-compose.langfuse.yml`
- Create: `.env.langfuse.example`
- Modify: `.gitignore`
- Modify: `QUICKSTART.md`

- [ ] **Step 1: Fetch the official pinned compose file**

The Langfuse v3 self-host stack (web, worker, postgres, clickhouse, redis, minio) is large and version-sensitive; use the canonical file rather than hand-authoring it. Run from the repo root:
```bash
curl -fsSL https://raw.githubusercontent.com/langfuse/langfuse/main/docker-compose.yml -o docker-compose.langfuse.yml
```
Open `docker-compose.langfuse.yml` and confirm it defines services `langfuse-web` and `langfuse-worker` plus `postgres`, `clickhouse`, `redis`, `minio`. If the upstream layout has changed materially, pin to a known tag instead (replace `main` with a release tag, e.g. `v3.x.y`).

- [ ] **Step 2: Create the secrets template**

Create `.env.langfuse.example`:
```
# Copy to .env.langfuse and fill with generated secrets (see QUICKSTART).
# Used only by docker-compose.langfuse.yml — NOT by the app.
LANGFUSE_SALT=
LANGFUSE_ENCRYPTION_KEY=
NEXTAUTH_SECRET=
CLICKHOUSE_PASSWORD=
MINIO_ROOT_PASSWORD=
POSTGRES_PASSWORD=
```

- [ ] **Step 3: Ignore the real secrets file**

Add to `.gitignore`:
```
.env.langfuse
```

- [ ] **Step 4: Document bring-up in QUICKSTART.md**

Append a section to `QUICKSTART.md`:
```markdown
## Observability (Langfuse, optional)

Self-hosted, off by default. To enable:

1. Generate secrets (Git Bash / WSL):
   ```bash
   cp .env.langfuse.example .env.langfuse
   for k in LANGFUSE_SALT LANGFUSE_ENCRYPTION_KEY NEXTAUTH_SECRET CLICKHOUSE_PASSWORD MINIO_ROOT_PASSWORD POSTGRES_PASSWORD; do
     echo "$k=$(openssl rand -hex 32)"
   done
   ```
   Paste the values into `.env.langfuse`. (`LANGFUSE_ENCRYPTION_KEY` must be 64 hex chars — `openssl rand -hex 32` satisfies this.)

2. Start the stack:
   ```bash
   docker compose -f docker-compose.langfuse.yml --env-file .env.langfuse up -d
   ```

3. Open http://localhost:3000, create an account + project, copy the project's
   public/secret keys.

4. In the app `.env`, set:
   ```
   ADVISORY_LANGFUSE_ENABLED=true
   LANGFUSE_HOST=http://localhost:3000
   LANGFUSE_PUBLIC_KEY=pk-...
   LANGFUSE_SECRET_KEY=sk-...
   ```

5. Run an advisory conversation; each run appears as a trace under the project,
   grouped by session.
```

- [ ] **Step 5: Validate the compose file parses**

Run:
```bash
docker compose -f docker-compose.langfuse.yml --env-file .env.langfuse.example config -q && echo OK
```
Expected: `OK` (no YAML/interpolation errors). This validates structure without starting containers.

- [ ] **Step 6: Smoke-test bring-up (manual, requires Docker)**

```bash
cp .env.langfuse.example .env.langfuse   # then fill with real secrets per QUICKSTART
docker compose -f docker-compose.langfuse.yml --env-file .env.langfuse up -d
```
Confirm http://localhost:3000 serves the Langfuse UI, then create a project and keys. (If the box cannot carry ClickHouse/Redis/MinIO, fall back to a Langfuse v2 single-container self-host per spec §8 — out of scope for this task unless that blocker hits.)

- [ ] **Step 7: Commit (template + compose + docs only — never `.env.langfuse`)**

```bash
git add docker-compose.langfuse.yml .env.langfuse.example .gitignore QUICKSTART.md
git commit -m "chore(observability): self-hosted Langfuse docker stack and docs"
```

---

### Task 9: Wire the root trace into the hybrid path (follow-on)

Mirrors Task 6 for `HybridDispatcher` so hybrid runs are traced too. Depends on Task 3.

**Files:**
- Modify: `services/chat/hybrid_dispatcher.py`
- Create: `tests/services/chat/test_hybrid_dispatcher_langfuse.py`

**Interfaces:**
- Consumes: `observability.run_trace.advisory_run_trace`.

- [ ] **Step 1: Write the failing test**

Create `tests/services/chat/test_hybrid_dispatcher_langfuse.py`:
```python
import contextlib

from services.chat import hybrid_dispatcher as hd
from services.chat.hybrid_dispatcher import HybridDispatcher
from services.chat.intent_router import IntentResult
from services.chat.models import ChatProfileState


class FakeRepository:
    def __init__(self):
        self.completed = None
        self.messages = []

    def mark_run_running(self, run_id):
        pass

    def complete_run(self, run_id, result_json, final_answer):
        self.completed = (run_id, result_json, final_answer)

    def append_message(self, session_token, role, content, kind="chat"):
        self.messages.append((session_token, role, kind, content))

    def update_session_status(self, session_token, status):
        pass


class FakeOrchestrator:
    def run(self, intent, profile_state, content, trace_run_id=None):
        return "SYNTH"


def test_hybrid_execute_opens_advisory_run_trace(monkeypatch):
    captured = {}

    @contextlib.contextmanager
    def fake_trace(run_id, session_token, user_message, intent=None, admission_year=None):
        captured["args"] = (run_id, session_token, user_message)
        captured["intent"] = intent
        yield None

    monkeypatch.setattr(hd, "advisory_run_trace", fake_trace)

    dispatcher = HybridDispatcher(repository=FakeRepository(), orchestrator=FakeOrchestrator())
    dispatcher.execute(
        session_token="s", run_id=5, content="hi",
        profile_state=ChatProfileState(admission_year=2026),
        intent=IntentResult(route="HYBRID", schools=[], topics=[], needs_advisory=True),
    )

    assert captured["args"] == (5, "s", "hi")
    assert captured["intent"] == "HYBRID"
    assert dispatcher.repository.completed[0] == 5
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/services/chat/test_hybrid_dispatcher_langfuse.py -v`
Expected: FAIL — `module 'services.chat.hybrid_dispatcher' has no attribute 'advisory_run_trace'`.

- [ ] **Step 3: Implement the wiring**

In `services/chat/hybrid_dispatcher.py`, add the import after `from services.chat.compare_orchestrator import CompareOrchestrator`:
```python
from observability.run_trace import advisory_run_trace
```
Replace the `execute` method body (lines 14–24) with:
```python
    def execute(self, session_token: str, run_id: int, content: str, profile_state, intent):
        try:
            self.repository.mark_run_running(run_id)
            with advisory_run_trace(
                run_id, session_token, content,
                intent=getattr(intent, "route", None),
                admission_year=getattr(profile_state, "admission_year", None),
            ):
                answer = self.orchestrator.run(intent, profile_state, content, trace_run_id=run_id)
            self.repository.complete_run(run_id, {"final_answer": answer, "kind": "hybrid"}, answer)
            self.repository.append_message(session_token, "assistant", answer, "assistant_result")
            self.repository.update_session_status(session_token, "completed")
        except Exception:
            logger.exception("hybrid run %s failed for session %s", run_id, session_token)
            self._mark_failed(session_token)
            raise
```

- [ ] **Step 5: Run the new test plus the existing hybrid suite**

Run: `python -m pytest tests/services/chat/test_hybrid_dispatcher_langfuse.py tests/services/chat/test_hybrid_dispatcher.py -v`
Expected: PASS (new 1 passed; existing hybrid tests still green).

- [ ] **Step 6: Commit**

```bash
git add services/chat/hybrid_dispatcher.py tests/services/chat/test_hybrid_dispatcher_langfuse.py
git commit -m "feat(observability): trace hybrid runs in Langfuse"
```

---

## Final verification

- [ ] Run the full suite with Langfuse disabled (the default): `python -m pytest -q`
  Expected: all green; no new failures versus before the work (the four scoping decisions guarantee zero behaviour change when `ADVISORY_LANGFUSE_ENABLED` is unset).
- [ ] End-to-end (manual): bring up the Langfuse stack (Task 8), set the four `.env` vars, run an advisory conversation, and confirm in the Langfuse UI: one trace per run named `advisory-run`, grouped by session id; six stage spans; a generation per Gemini call carrying token usage; retries/fallback visible as separate generations.

## Notes on sequencing

- Tasks 1–7 are the phase-1 deliverable and are strictly ordered by dependency
  (1 → 2 → 3 → {4, 5, 6} → 7). Tasks 4, 5, 6 are mutually independent once 3 lands.
- Task 8 (Docker) has no code dependency and may be done first if you want to
  watch traces land as you implement.
- Task 9 (hybrid) is an optional follow-on; phase-1 observability is complete
  without it (advisory path fully traced).
- Open decision carried from the spec (§13): Langfuse v3 (this plan) vs a lighter
  v2 single-container self-host. Only revisit if Task 8's stack is too heavy for
  the box.
```