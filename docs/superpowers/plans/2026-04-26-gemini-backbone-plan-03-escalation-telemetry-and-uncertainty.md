# Gemini Backbone Plan 03: Escalation, Telemetry, And Uncertainty Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add selective fallback for higher-risk agents, log retry/escalation costs, and return explicit uncertainty instead of fabricated confidence.

**Architecture:** Extend `LLMGateway` with failure classification, one same-model retry for structural failures, selective stronger-model fallback for `reasoning_agent` and `policy_agent`, and telemetry hooks. Keep the gateway decision logic centralized and let agents consume normalized uncertainty output instead of provider-specific errors.

**Tech Stack:** Python, Pydantic, `tenacity`, `pytest`, `monkeypatch`

---

### Task 1: Add Failure Classification, Retry, And Fallback Routing

**Files:**
- Modify: `services/inference/models.py`
- Modify: `services/inference/registry.py`
- Modify: `services/inference/gateway.py`
- Test: `tests/services/inference/test_gateway_retry_and_fallback.py`

- [ ] **Step 1: Write the failing test**

```python
from services.inference.gateway import LLMGateway
from services.inference.models import InferenceRequest, InferenceResult
from services.inference.registry import ModelRegistry


class RetryThenFallbackProvider:
    def __init__(self):
        self.calls = []

    def generate(self, request, policy):
        self.calls.append(policy.primary_model)
        if len(self.calls) == 1:
            return InferenceResult(
                agent_name=request.agent_name,
                model=policy.primary_model,
                provider="fake",
                content="{bad json",
                failure_type="STRUCTURE_FAILURE",
            )
        return InferenceResult(
            agent_name=request.agent_name,
            model=policy.primary_model,
            provider="fake",
            content='{"decision":"fallback-success"}',
            parsed_data={"decision": "fallback-success"},
        )


def test_gateway_retries_structure_failure_then_succeeds():
    registry = ModelRegistry(
        default_model="gemini-2.5-flash-lite",
        agent_overrides={
            "reasoning_agent": {
                "primary_model": "gemini-2.5-flash-lite",
                "fallback_model": "gemini-2.5-flash",
                "allow_fallback": True,
                "max_retries": 1,
            }
        },
    )
    provider = RetryThenFallbackProvider()
    gateway = LLMGateway(registry=registry, providers={"gemini": provider})

    result = gateway.run(
        InferenceRequest(
            agent_name="reasoning_agent",
            task_type="recommendation_reasoning",
            system_prompt="test",
            user_prompt="test",
            output_mode="json",
        )
    )

    assert result.parsed_data == {"decision": "fallback-success"}
    assert provider.calls == ["gemini-2.5-flash-lite", "gemini-2.5-flash-lite"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/services/inference/test_gateway_retry_and_fallback.py -v`
Expected: FAIL because `LLMGateway.run()` only makes one provider call

- [ ] **Step 3: Write minimal implementation**

```python
# services/inference/models.py
class InferenceResult(BaseModel):
    agent_name: str
    model: str
    provider: str
    content: str
    parsed_data: Optional[Dict[str, Any]] = None
    failure_type: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    uncertainty_reasons: List[str] = Field(default_factory=list)
```

```python
# services/inference/gateway.py
class LLMGateway:
    def __init__(self, registry, providers=None, telemetry=None):
        self.registry = registry
        self.providers = providers or {"gemini": GeminiProvider()}
        self.telemetry = telemetry

    def run(self, request):
        policy = self.registry.resolve(request.agent_name)
        provider = self.providers["gemini"]

        for attempt in range(policy.max_retries + 1):
            result = provider.generate(request, policy)
            if result.failure_type != "STRUCTURE_FAILURE":
                return result

        if policy.allow_fallback and policy.fallback_model:
            fallback_policy = policy.model_copy(update={"primary_model": policy.fallback_model})
            return provider.generate(request, fallback_policy)

        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/services/inference/test_gateway_retry_and_fallback.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/inference/models.py services/inference/registry.py services/inference/gateway.py tests/services/inference/test_gateway_retry_and_fallback.py
git commit -m "feat: add retry and fallback routing to gateway"
```

### Task 2: Add Policy Ambiguity Escalation And Explicit Uncertainty Result Handling

**Files:**
- Create: `services/policy_inference_service.py`
- Modify: `agents/policy_agent.py`
- Modify: `state.py`
- Modify: `tests/agents/test_policy_agent.py`
- Test: `tests/services/test_policy_inference_service.py`

- [ ] **Step 1: Write the failing test**

```python
from services.inference.models import InferenceResult
from services.policy_inference_service import interpret_policy_ambiguity


class FakeGateway:
    def run(self, request):
        return InferenceResult(
            agent_name=request.agent_name,
            model="gemini-2.5-flash",
            provider="fake",
            content='{"warnings":["Ambiguous quota wording."],"requires_human_verification":true}',
            parsed_data={
                "warnings": ["Ambiguous quota wording."],
                "requires_human_verification": True,
            },
        )


def test_interpret_policy_ambiguity_returns_structured_warning():
    parsed = interpret_policy_ambiguity(
        user_query="Chi tieu xet tuyen co thay doi khong?",
        conflicts=["Quota conflict for Khoa hoc May tinh at HUST"],
        gateway=FakeGateway(),
    )

    assert parsed["requires_human_verification"] is True
    assert parsed["warnings"] == ["Ambiguous quota wording."]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/services/test_policy_inference_service.py -v`
Expected: FAIL with `ImportError` for `policy_inference_service`

- [ ] **Step 3: Write minimal implementation**

```python
# services/policy_inference_service.py
import json

from services.inference.models import InferenceRequest


POLICY_SYSTEM_PROMPT = """
Interpret only ambiguous policy text or conflicting evidence.
Return JSON with keys: warnings and requires_human_verification.
Never promise admission certainty.
"""


def interpret_policy_ambiguity(user_query: str, conflicts, gateway):
    payload = {"user_query": user_query, "conflicts": conflicts}
    result = gateway.run(
        InferenceRequest(
            agent_name="policy_agent",
            task_type="policy_ambiguity",
            system_prompt=POLICY_SYSTEM_PROMPT.strip(),
            user_prompt=json.dumps(payload, ensure_ascii=False),
            output_mode="json",
            temperature=0.0,
        )
    )
    return result.parsed_data or {"warnings": [], "requires_human_verification": False}
```

```python
# state.py
class AgentState(BaseModel):
    ...
    inference_warnings: List[str] = Field(default_factory=list)
    uncertainty_reasons: List[str] = Field(default_factory=list)
```

```python
# agents/policy_agent.py
from services import build_default_gateway
from services.policy_inference_service import interpret_policy_ambiguity
from services.policy_service import evaluate_policy_guardrails


def policy_agent(state: AgentState):
    decision, filtered_recommendations = evaluate_policy_guardrails(
        user_query=state.user_query,
        profile=state.student_profile,
        candidates=state.retrieved_programs,
        recommendations=state.ranked_recommendations,
        conflicts=state.conflicts,
    )

    if state.conflicts:
        gateway = build_default_gateway()
        ambiguity = interpret_policy_ambiguity(state.user_query, state.conflicts, gateway)
        decision.warnings.extend(ambiguity["warnings"])
        if ambiguity["requires_human_verification"]:
            state.uncertainty_reasons.append("policy_ambiguity_requires_verification")

    state.policy_decision = decision
    state.ranked_recommendations = filtered_recommendations
    return state
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/services/test_policy_inference_service.py tests/agents/test_policy_agent.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/policy_inference_service.py agents/policy_agent.py state.py tests/services/test_policy_inference_service.py tests/agents/test_policy_agent.py
git commit -m "feat: add policy ambiguity escalation handling"
```

### Task 3: Add Telemetry And End-To-End Uncertainty Regression Coverage

**Files:**
- Create: `services/inference/telemetry.py`
- Modify: `services/inference/factory.py`
- Modify: `scripts/run_advisory_demo.py`
- Modify: `tests/e2e/test_advisory_flow.py`
- Test: `tests/services/inference/test_telemetry.py`

- [ ] **Step 1: Write the failing test**

```python
from services.inference.telemetry import InferenceTelemetry


def test_telemetry_records_retry_and_fallback():
    telemetry = InferenceTelemetry()

    telemetry.record(
        agent_name="reasoning_agent",
        task_type="recommendation_reasoning",
        provider="gemini",
        model="gemini-2.5-flash",
        retried=True,
        fell_back=True,
        status="success",
    )

    assert telemetry.events[0]["agent_name"] == "reasoning_agent"
    assert telemetry.events[0]["fell_back"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/services/inference/test_telemetry.py -v`
Expected: FAIL with `ImportError` for `InferenceTelemetry`

- [ ] **Step 3: Write minimal implementation**

```python
# services/inference/telemetry.py
from dataclasses import dataclass, field


@dataclass
class InferenceTelemetry:
    events: list[dict] = field(default_factory=list)

    def record(self, **event):
        self.events.append(event)
```

```python
# services/inference/factory.py
from services.inference.telemetry import InferenceTelemetry


def build_default_gateway() -> LLMGateway:
    registry = ModelRegistry(
        default_model="gemini-2.5-flash-lite",
        agent_overrides={
            "profile_agent": {"output_mode": "json", "max_retries": 1},
            "reasoning_agent": {
                "output_mode": "json",
                "max_retries": 1,
                "allow_fallback": True,
                "fallback_model": "gemini-2.5-flash",
            },
            "policy_agent": {
                "output_mode": "json",
                "max_retries": 1,
                "allow_fallback": True,
                "fallback_model": "gemini-2.5-flash",
            },
            "explanation_agent": {"output_mode": "free_text", "max_retries": 1},
        },
    )
    return LLMGateway(registry=registry, telemetry=InferenceTelemetry())
```

```python
# scripts/run_advisory_demo.py
def run(query: str, admission_year: int = 2026, json_output: bool = False) -> int:
    ...
    if state.get("uncertainty_reasons"):
        print("Uncertainty:")
        print(json.dumps(state["uncertainty_reasons"], ensure_ascii=False, indent=2))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/services/inference/test_telemetry.py tests/e2e/test_advisory_flow.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/inference/telemetry.py services/inference/factory.py scripts/run_advisory_demo.py tests/services/inference/test_telemetry.py tests/e2e/test_advisory_flow.py
git commit -m "feat: add inference telemetry and uncertainty reporting"
```

## Self-Review

Spec coverage in this plan:
- Retry on structural failures: Task 1.
- Selective fallback for `reasoning_agent` and `policy_agent`: Tasks 1 and 3.
- Explicit uncertainty state: Tasks 2 and 3.
- Observability: Task 3.

Intentional exclusions from this plan:
- No fallback for `profile_agent` or `explanation_agent`.
- No ingestion-agent migration yet.

Plan complete and saved to `docs/superpowers/plans/2026-04-26-gemini-backbone-plan-03-escalation-telemetry-and-uncertainty.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
