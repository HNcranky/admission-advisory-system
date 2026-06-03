# Slice 05 — Inference telemetry wiring

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the gateway actually record telemetry. `InferenceTelemetry.record(**event)` and the `self.telemetry` field already exist but are never called; wire `gateway.run()` to record one event per attempt and on fallback.

**Architecture:** Add a private `_record(...)` helper to `LLMGateway` and call it inside the retry/fallback loop, guarded for `telemetry is None`.

**Tech Stack:** Python 3.12, pytest.

**Spec:** `docs/superpowers/specs/2026-05-29-tech-debt-cleanup-design.md` (item A3)

**Depends on:** Slice 03 (the `STRUCTURE_FAILURE` contract drives the retry path being recorded). **Branch:** `chore/stabilize-cleanup`.

---

## Task 1: Record per-attempt telemetry in `gateway.run()`

**Files:**
- Modify: `services/inference/gateway.py:15-28`
- Test: `tests/services/inference/test_gateway_telemetry.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/services/inference/test_gateway_telemetry.py`:

```python
from services.inference.gateway import LLMGateway
from services.inference.models import InferenceRequest, InferenceResult
from services.inference.registry import ModelRegistry
from services.inference.telemetry import InferenceTelemetry


class _FlakyProvider:
    """First call returns STRUCTURE_FAILURE, second call succeeds."""

    def __init__(self):
        self.calls = 0

    def is_available(self):
        return True

    def generate(self, request, policy):
        self.calls += 1
        failure = "STRUCTURE_FAILURE" if self.calls == 1 else None
        return InferenceResult(
            agent_name=request.agent_name,
            model=policy.primary_model,
            provider="fake",
            content="{}",
            parsed_data={} if failure is None else None,
            failure_type=failure,
        )


def _gateway(provider, telemetry):
    registry = ModelRegistry(
        default_model="m",
        agent_overrides={"profile_agent": {"output_mode": "json", "max_retries": 1}},
    )
    return LLMGateway(registry=registry, providers={"gemini": provider}, telemetry=telemetry)


def test_gateway_records_one_event_per_attempt():
    telemetry = InferenceTelemetry()
    provider = _FlakyProvider()
    gateway = _gateway(provider, telemetry)

    gateway.run(
        InferenceRequest(
            agent_name="profile_agent",
            task_type="profile_extraction",
            system_prompt="s",
            user_prompt="u",
            output_mode="json",
        )
    )

    assert len(telemetry.events) == 2
    assert telemetry.events[0]["failure_type"] == "STRUCTURE_FAILURE"
    assert telemetry.events[0]["attempt"] == 0
    assert telemetry.events[1]["failure_type"] is None
    assert telemetry.events[1]["attempt"] == 1
    assert all(event["agent_name"] == "profile_agent" for event in telemetry.events)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/services/inference/test_gateway_telemetry.py -v`
Expected: FAIL — `telemetry.events` is empty; `gateway.run` never records.

- [ ] **Step 3: Wire telemetry into `gateway.run`**

Replace the `run` method of `services/inference/gateway.py` (lines 15-28) with the following (adds the loop recording, a fallback recording, and a `_record` helper):

```python
    def run(self, request):
        policy = self.registry.resolve(request.agent_name)
        provider = self.providers["gemini"]

        result = None
        for attempt in range(policy.max_retries + 1):
            result = provider.generate(request, policy)
            self._record(request, policy.primary_model, attempt, result.failure_type, used_fallback=False)
            if result.failure_type != "STRUCTURE_FAILURE":
                return result

        if policy.allow_fallback and policy.fallback_model:
            fallback_policy = policy.model_copy(update={"primary_model": policy.fallback_model})
            result = provider.generate(request, fallback_policy)
            self._record(
                request, fallback_policy.primary_model, policy.max_retries + 1,
                result.failure_type, used_fallback=True,
            )
            return result

        return result

    def _record(self, request, model, attempt, failure_type, used_fallback):
        if self.telemetry is None:
            return
        self.telemetry.record(
            agent_name=request.agent_name,
            model=model,
            attempt=attempt,
            failure_type=failure_type,
            used_fallback=used_fallback,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/services/inference/test_gateway_telemetry.py -v`
Expected: PASS.

- [ ] **Step 5: Run the inference suite for regressions**

Run: `.venv/Scripts/python.exe -m pytest tests/services/inference -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add services/inference/gateway.py tests/services/inference/test_gateway_telemetry.py
git commit -m "feat: record per-attempt inference telemetry in the gateway"
```
