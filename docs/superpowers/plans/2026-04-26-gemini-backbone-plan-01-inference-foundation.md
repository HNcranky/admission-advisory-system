# Gemini Backbone Plan 01: Inference Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a shared inference package that makes `gemini-2.5-flash-lite` the default model behind a centralized registry and gateway.

**Architecture:** Create a new `services/inference/` package with typed request/result models, a static registry, and a single Gemini provider adapter behind a gateway. This slice is deliberately isolated from the existing advisory agents so the new backbone can be tested before any behavior migration starts.

**Tech Stack:** Python, Pydantic, `google-generativeai`, `tenacity`, `pytest`, `monkeypatch`

---

### Task 1: Define Shared Inference Contracts And Static Registry

**Files:**
- Create: `services/inference/__init__.py`
- Create: `services/inference/models.py`
- Create: `services/inference/registry.py`
- Test: `tests/services/inference/test_registry.py`

- [ ] **Step 1: Write the failing test**

```python
from services.inference.registry import ModelRegistry


def test_registry_resolves_default_and_agent_override():
    registry = ModelRegistry(
        default_model="gemini-2.5-flash-lite",
        agent_overrides={
            "reasoning_agent": {
                "primary_model": "gemini-2.5-flash-lite",
                "fallback_model": "gemini-2.5-flash",
                "allow_fallback": True,
                "output_mode": "json",
            }
        },
    )

    profile_policy = registry.resolve("profile_agent")
    reasoning_policy = registry.resolve("reasoning_agent")

    assert profile_policy.agent_name == "profile_agent"
    assert profile_policy.primary_model == "gemini-2.5-flash-lite"
    assert profile_policy.allow_fallback is False
    assert reasoning_policy.fallback_model == "gemini-2.5-flash"
    assert reasoning_policy.allow_fallback is True
    assert reasoning_policy.output_mode == "json"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/services/inference/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.inference'`

- [ ] **Step 3: Write minimal implementation**

```python
# services/inference/models.py
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class InferenceRequest(BaseModel):
    agent_name: str
    task_type: str
    system_prompt: str
    user_prompt: str
    output_mode: str = "free_text"
    schema_name: Optional[str] = None
    temperature: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class InferencePolicy(BaseModel):
    agent_name: str
    primary_model: str
    fallback_model: Optional[str] = None
    allow_fallback: bool = False
    output_mode: str = "free_text"
    max_retries: int = 1


class InferenceResult(BaseModel):
    agent_name: str
    model: str
    provider: str
    content: str
    parsed_data: Optional[Dict[str, Any]] = None
    failure_type: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
```

```python
# services/inference/registry.py
from typing import Dict

from pydantic import BaseModel, Field

from services.inference.models import InferencePolicy


class ModelRegistry(BaseModel):
    default_model: str
    agent_overrides: Dict[str, Dict[str, object]] = Field(default_factory=dict)

    def resolve(self, agent_name: str) -> InferencePolicy:
        override = self.agent_overrides.get(agent_name, {})
        return InferencePolicy(
            agent_name=agent_name,
            primary_model=str(override.get("primary_model", self.default_model)),
            fallback_model=override.get("fallback_model"),
            allow_fallback=bool(override.get("allow_fallback", False)),
            output_mode=str(override.get("output_mode", "free_text")),
            max_retries=int(override.get("max_retries", 1)),
        )
```

```python
# services/inference/__init__.py
from services.inference.models import InferencePolicy, InferenceRequest, InferenceResult
from services.inference.registry import ModelRegistry

__all__ = ["InferencePolicy", "InferenceRequest", "InferenceResult", "ModelRegistry"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/services/inference/test_registry.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/inference/__init__.py services/inference/models.py services/inference/registry.py tests/services/inference/test_registry.py
git commit -m "feat: add inference registry foundation"
```

### Task 2: Add Gemini Provider Adapter And Central Gateway

**Files:**
- Create: `services/inference/providers/__init__.py`
- Create: `services/inference/providers/base.py`
- Create: `services/inference/providers/gemini_provider.py`
- Create: `services/inference/gateway.py`
- Test: `tests/services/inference/test_gateway.py`

- [ ] **Step 1: Write the failing test**

```python
from services.inference.gateway import LLMGateway
from services.inference.models import InferenceRequest, InferenceResult
from services.inference.registry import ModelRegistry


class FakeProvider:
    def generate(self, request, policy):
        return InferenceResult(
            agent_name=request.agent_name,
            model=policy.primary_model,
            provider="fake",
            content='{"summary":"ok"}',
            parsed_data={"summary": "ok"},
        )


def test_gateway_uses_registry_and_provider():
    registry = ModelRegistry(default_model="gemini-2.5-flash-lite")
    gateway = LLMGateway(registry=registry, providers={"gemini": FakeProvider()})

    result = gateway.run(
        InferenceRequest(
            agent_name="profile_agent",
            task_type="profile_extraction",
            system_prompt="Extract profile",
            user_prompt="Em duoc 27 diem A00",
            output_mode="json",
        )
    )

    assert result.provider == "fake"
    assert result.model == "gemini-2.5-flash-lite"
    assert result.parsed_data == {"summary": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/services/inference/test_gateway.py -v`
Expected: FAIL with `ImportError` for `LLMGateway`

- [ ] **Step 3: Write minimal implementation**

```python
# services/inference/providers/base.py
from abc import ABC, abstractmethod


class BaseInferenceProvider(ABC):
    @abstractmethod
    def generate(self, request, policy):
        raise NotImplementedError
```

```python
# services/inference/providers/gemini_provider.py
import json
import os

import google.generativeai as genai

from services.inference.models import InferenceResult


class GeminiProvider:
    provider_name = "gemini"

    def __init__(self, api_key: str | None = None):
        key = api_key or os.getenv("GEMINI_API_KEY", "")
        if key:
            genai.configure(api_key=key)
        self._api_key_present = bool(key)

    def generate(self, request, policy):
        if not self._api_key_present:
            raise RuntimeError("GEMINI_API_KEY is not configured")

        model = genai.GenerativeModel(policy.primary_model)
        response = model.generate_content(
            [request.system_prompt, request.user_prompt],
            generation_config={"temperature": request.temperature},
        )
        text = getattr(response, "text", "") or ""
        parsed = json.loads(text) if request.output_mode == "json" else None
        return InferenceResult(
            agent_name=request.agent_name,
            model=policy.primary_model,
            provider=self.provider_name,
            content=text,
            parsed_data=parsed,
        )
```

```python
# services/inference/gateway.py
from services.inference.providers.gemini_provider import GeminiProvider


class LLMGateway:
    def __init__(self, registry, providers=None):
        self.registry = registry
        self.providers = providers or {"gemini": GeminiProvider()}

    def run(self, request):
        policy = self.registry.resolve(request.agent_name)
        provider = self.providers["gemini"]
        return provider.generate(request, policy)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/services/inference/test_gateway.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/inference/providers/__init__.py services/inference/providers/base.py services/inference/providers/gemini_provider.py services/inference/gateway.py tests/services/inference/test_gateway.py
git commit -m "feat: add gemini gateway adapter"
```

### Task 3: Add Repository-Level Factory For Shared Gateway Construction

**Files:**
- Create: `services/inference/factory.py`
- Modify: `services/__init__.py`
- Test: `tests/services/inference/test_factory.py`

- [ ] **Step 1: Write the failing test**

```python
from services.inference.factory import build_default_gateway


def test_build_default_gateway_has_expected_agent_defaults():
    gateway = build_default_gateway()

    profile_policy = gateway.registry.resolve("profile_agent")
    reasoning_policy = gateway.registry.resolve("reasoning_agent")
    explanation_policy = gateway.registry.resolve("explanation_agent")

    assert profile_policy.primary_model == "gemini-2.5-flash-lite"
    assert reasoning_policy.allow_fallback is False
    assert explanation_policy.output_mode == "free_text"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/services/inference/test_factory.py -v`
Expected: FAIL with `ImportError` for `build_default_gateway`

- [ ] **Step 3: Write minimal implementation**

```python
# services/inference/factory.py
from services.inference.gateway import LLMGateway
from services.inference.registry import ModelRegistry


def build_default_gateway() -> LLMGateway:
    registry = ModelRegistry(
        default_model="gemini-2.5-flash-lite",
        agent_overrides={
            "profile_agent": {"output_mode": "json", "max_retries": 1},
            "reasoning_agent": {"output_mode": "json", "max_retries": 1},
            "policy_agent": {"output_mode": "json", "max_retries": 1},
            "explanation_agent": {"output_mode": "free_text", "max_retries": 1},
        },
    )
    return LLMGateway(registry=registry)
```

```python
# services/__init__.py
from services.inference.factory import build_default_gateway

__all__ = ["build_default_gateway"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/services/inference/test_factory.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/inference/factory.py services/__init__.py tests/services/inference/test_factory.py
git commit -m "feat: add default inference gateway factory"
```

## Self-Review

Spec coverage in this plan:
- Central model registry: covered by Task 1.
- Shared gateway entrypoint: covered by Task 2.
- Default Gemini backbone: covered by Task 3.

Intentional exclusions from this plan:
- No advisory agent code changes yet.
- No fallback routing yet.
- No telemetry yet.

Plan complete and saved to `docs/superpowers/plans/2026-04-26-gemini-backbone-plan-01-inference-foundation.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
