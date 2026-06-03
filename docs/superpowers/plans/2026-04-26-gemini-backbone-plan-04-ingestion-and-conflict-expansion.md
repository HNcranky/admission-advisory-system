# Gemini Backbone Plan 04: Ingestion And Conflict Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the same inference backbone to ingestion extraction and conflict-resolution flows without introducing a second routing layer.

**Architecture:** Reuse `services/inference/` and add narrowly scoped gateway consumers only where the broader architecture benefits from LLM help: messy extraction, ambiguity-aware normalization, and conflict resolution rationale. Deterministic validation, evidence ranking, and direct field comparison remain code-driven.

**Tech Stack:** Python, Pydantic, `pytest`, existing ingestion pipeline modules

---

### Task 1: Add Extraction-Agent Gateway Entry Point For Difficult Source Parsing

**Files:**
- Create: `ingestion/extractors/llm_extraction_service.py`
- Modify: `ingestion/extractors/admission_extractor.py`
- Modify: `services/inference/factory.py`
- Test: `tests/ingestion/test_llm_extraction_service.py`

- [ ] **Step 1: Write the failing test**

```python
from services.inference.models import InferenceResult
from ingestion.extractors.llm_extraction_service import extract_admission_facts_with_gateway


class FakeGateway:
    def run(self, request):
        return InferenceResult(
            agent_name=request.agent_name,
            model="gemini-2.5-flash-lite",
            provider="fake",
            content='{"facts":[{"program_name":"Khoa hoc May tinh","admission_method":"thpt_score","subject_combinations":["A00","A01"]}]}',
            parsed_data={
                "facts": [
                    {
                        "program_name": "Khoa hoc May tinh",
                        "admission_method": "thpt_score",
                        "subject_combinations": ["A00", "A01"],
                    }
                ]
            },
        )


def test_extract_admission_facts_with_gateway_returns_fact_list():
    facts = extract_admission_facts_with_gateway(
        source_text="Chi tieu nganh Khoa hoc May tinh to hop A00 A01",
        gateway=FakeGateway(),
    )

    assert facts[0]["program_name"] == "Khoa hoc May tinh"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ingestion/test_llm_extraction_service.py -v`
Expected: FAIL with `ImportError` for `llm_extraction_service`

- [ ] **Step 3: Write minimal implementation**

```python
# ingestion/extractors/llm_extraction_service.py
import json

from services.inference.models import InferenceRequest


EXTRACTION_SYSTEM_PROMPT = """
Extract Vietnamese admission facts from noisy source text.
Return JSON with key facts. Each fact must include program_name, admission_method, and subject_combinations.
"""


def extract_admission_facts_with_gateway(source_text: str, gateway):
    result = gateway.run(
        InferenceRequest(
            agent_name="extraction_agent",
            task_type="document_extraction",
            system_prompt=EXTRACTION_SYSTEM_PROMPT.strip(),
            user_prompt=json.dumps({"source_text": source_text}, ensure_ascii=False),
            output_mode="json",
            temperature=0.0,
        )
    )
    return (result.parsed_data or {}).get("facts", [])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ingestion/test_llm_extraction_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ingestion/extractors/llm_extraction_service.py ingestion/extractors/admission_extractor.py services/inference/factory.py tests/ingestion/test_llm_extraction_service.py
git commit -m "feat: add gateway-backed extraction path for difficult sources"
```

### Task 2: Add Conflict-Resolution Rationale Through The Shared Gateway

**Files:**
- Create: `services/conflict_resolution_service.py`
- Modify: `agents/conflict_agent.py`
- Modify: `services/inference/factory.py`
- Test: `tests/services/test_conflict_resolution_service.py`

- [ ] **Step 1: Write the failing test**

```python
from services.conflict_resolution_service import resolve_conflicts_with_gateway
from services.inference.models import InferenceResult


class FakeGateway:
    def run(self, request):
        return InferenceResult(
            agent_name=request.agent_name,
            model="gemini-2.5-flash",
            provider="fake",
            content='{"resolution":"Prefer higher-trust HUST source.","uncertainty_reasons":[]}',
            parsed_data={
                "resolution": "Prefer higher-trust HUST source.",
                "uncertainty_reasons": [],
            },
        )


def test_resolve_conflicts_with_gateway_returns_resolution():
    parsed = resolve_conflicts_with_gateway(
        conflicts=["Quota conflict for Khoa hoc May tinh at HUST"],
        gateway=FakeGateway(),
    )

    assert parsed["resolution"] == "Prefer higher-trust HUST source."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/services/test_conflict_resolution_service.py -v`
Expected: FAIL with `ImportError` for `conflict_resolution_service`

- [ ] **Step 3: Write minimal implementation**

```python
# services/conflict_resolution_service.py
import json

from services.inference.models import InferenceRequest


RESOLUTION_SYSTEM_PROMPT = """
Resolve admission-evidence conflicts conservatively.
Return JSON with keys: resolution and uncertainty_reasons.
Prefer authoritative evidence and return uncertainty when evidence stays unresolved.
"""


def resolve_conflicts_with_gateway(conflicts, gateway):
    result = gateway.run(
        InferenceRequest(
            agent_name="resolution_agent",
            task_type="conflict_resolution",
            system_prompt=RESOLUTION_SYSTEM_PROMPT.strip(),
            user_prompt=json.dumps({"conflicts": conflicts}, ensure_ascii=False),
            output_mode="json",
            temperature=0.0,
        )
    )
    return result.parsed_data or {"resolution": "", "uncertainty_reasons": ["resolution_failed"]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/services/test_conflict_resolution_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/conflict_resolution_service.py agents/conflict_agent.py services/inference/factory.py tests/services/test_conflict_resolution_service.py
git commit -m "feat: add gateway-backed conflict resolution rationale"
```

### Task 3: Lock In Deterministic Boundaries With Regression Tests

**Files:**
- Modify: `tests/services/test_retrieval_service.py`
- Modify: `tests/e2e/test_advisory_flow.py`
- Create: `tests/ingestion/test_inference_boundaries.py`

- [ ] **Step 1: Write the failing test**

```python
def test_retrieval_service_stays_deterministic_without_gateway_calls():
    filters = {
        "admission_year": 2026,
        "preferred_majors": ["computer_science"],
        "preferred_schools": ["hust"],
        "subject_combination": "A00",
    }

    assert filters["preferred_majors"] == ["computer_science"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ingestion/test_inference_boundaries.py -v`
Expected: FAIL because the new test file does not exist yet

- [ ] **Step 3: Write minimal implementation**

```python
# tests/ingestion/test_inference_boundaries.py
from services.inference.factory import build_default_gateway


def test_gateway_registry_has_no_retrieval_agent_override():
    gateway = build_default_gateway()
    policy = gateway.registry.resolve("retrieval_agent")

    assert policy.primary_model == "gemini-2.5-flash-lite"
    assert policy.allow_fallback is False


def test_gateway_registry_enables_resolution_agent_fallback():
    gateway = build_default_gateway()
    policy = gateway.registry.resolve("resolution_agent")

    assert policy.allow_fallback is True
    assert policy.fallback_model == "gemini-2.5-flash"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ingestion/test_inference_boundaries.py tests/services/test_retrieval_service.py tests/e2e/test_advisory_flow.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/ingestion/test_inference_boundaries.py tests/services/test_retrieval_service.py tests/e2e/test_advisory_flow.py
git commit -m "test: lock deterministic inference boundaries"
```

## Self-Review

Spec coverage in this plan:
- Extraction-agent support: Task 1.
- Resolution-agent support: Task 2.
- Deterministic validation, comparison, and retrieval boundaries: Task 3.

Intentional exclusions from this plan:
- No dynamic free-form router.
- No replacement of deterministic validation with LLM-only behavior.

Plan complete and saved to `docs/superpowers/plans/2026-04-26-gemini-backbone-plan-04-ingestion-and-conflict-expansion.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
