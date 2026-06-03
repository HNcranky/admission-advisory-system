# Gemini Backbone Plan 02: Advisory Agent Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route the LLM-suitable advisory responsibilities through the shared gateway while preserving deterministic retrieval and policy filtering.

**Architecture:** Keep `services/retrieval_service.py` and the hard guardrails in `services/policy_service.py` deterministic. Move profile extraction, recommendation reasoning, and response drafting behind small service helpers that build prompts, call `LLMGateway`, and validate returned JSON before updating `AgentState`.

**Tech Stack:** Python, Pydantic, `pytest`, `monkeypatch`, existing `langgraph` graph

---

### Task 1: Migrate Profile Extraction To Gateway-Backed Structured Output

**Files:**
- Create: `services/profile_inference_service.py`
- Modify: `agents/profile_agent.py`
- Modify: `tests/agents/test_profile_agent.py`
- Test: `tests/services/test_profile_inference_service.py`

- [ ] **Step 1: Write the failing test**

```python
from services.profile_inference_service import build_profile_with_gateway
from services.inference.models import InferenceResult


class FakeGateway:
    def run(self, request):
        return InferenceResult(
            agent_name=request.agent_name,
            model="gemini-2.5-flash-lite",
            provider="fake",
            content='{"total_score":27,"subject_combination":"A00","preferred_majors":["computer_science"],"preferred_schools":["hust"],"missing_slots":[]}',
            parsed_data={
                "total_score": 27,
                "subject_combination": "A00",
                "preferred_majors": ["computer_science"],
                "preferred_schools": ["hust"],
                "missing_slots": [],
            },
        )


def test_build_profile_with_gateway_returns_student_profile():
    profile = build_profile_with_gateway(
        user_query="Em duoc 27 diem A00 muon hoc Cong nghe thong tin o HUST",
        gateway=FakeGateway(),
    )

    assert profile.total_score == 27
    assert profile.subject_combination == "A00"
    assert profile.preferred_majors == ["computer_science"]
    assert profile.preferred_schools == ["hust"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/services/test_profile_inference_service.py -v`
Expected: FAIL with `ImportError` for `profile_inference_service`

- [ ] **Step 3: Write minimal implementation**

```python
# services/profile_inference_service.py
from agents.models import StudentProfile
from services.inference.models import InferenceRequest


PROFILE_SYSTEM_PROMPT = """
Extract a Vietnamese admission-advisory student profile.
Return JSON with keys: total_score, subject_combination, preferred_majors, preferred_schools, missing_slots.
Use null for unknown scalar values and [] for unknown list values.
"""


def build_profile_with_gateway(user_query: str, gateway) -> StudentProfile:
    result = gateway.run(
        InferenceRequest(
            agent_name="profile_agent",
            task_type="profile_extraction",
            system_prompt=PROFILE_SYSTEM_PROMPT.strip(),
            user_prompt=user_query,
            output_mode="json",
            temperature=0.0,
        )
    )
    return StudentProfile(**(result.parsed_data or {}))
```

```python
# agents/profile_agent.py
from services import build_default_gateway
from services.profile_inference_service import build_profile_with_gateway
from state import AgentState


def profile_agent(state: AgentState):
    gateway = build_default_gateway()
    state.student_profile = build_profile_with_gateway(state.user_query, gateway)
    state.retrieval_missing_data = list(state.student_profile.missing_slots)
    return state
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/services/test_profile_inference_service.py tests/agents/test_profile_agent.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/profile_inference_service.py agents/profile_agent.py tests/services/test_profile_inference_service.py tests/agents/test_profile_agent.py
git commit -m "feat: route profile extraction through inference gateway"
```

### Task 2: Migrate Recommendation Reasoning To Gateway With Structured Ranking Output

**Files:**
- Create: `services/reasoning_inference_service.py`
- Modify: `agents/reasoning_agent.py`
- Modify: `tests/agents/test_reasoning_agent.py`
- Test: `tests/services/test_reasoning_inference_service.py`

- [ ] **Step 1: Write the failing test**

```python
from agents.models import CandidateProgram, Evidence, StudentProfile
from services.inference.models import InferenceResult
from services.reasoning_inference_service import reason_candidates_with_gateway


class FakeGateway:
    def run(self, request):
        return InferenceResult(
            agent_name=request.agent_name,
            model="gemini-2.5-flash-lite",
            provider="fake",
            content='{"eligibility_checks":[{"candidate_id":"hust:1","eligible":true,"reasons":["Subject combination matches."],"risks":[],"confidence":0.9}],"ranked_recommendations":[{"candidate_id":"hust:1","band":"safe","score":0.91,"summary":"Strong fit.","reasons":["Preferred major matches."],"cautions":[]}]}',
            parsed_data={
                "eligibility_checks": [
                    {
                        "candidate_id": "hust:1",
                        "eligible": True,
                        "reasons": ["Subject combination matches."],
                        "risks": [],
                        "confidence": 0.9,
                    }
                ],
                "ranked_recommendations": [
                    {
                        "candidate_id": "hust:1",
                        "band": "safe",
                        "score": 0.91,
                        "summary": "Strong fit.",
                        "reasons": ["Preferred major matches."],
                        "cautions": [],
                    }
                ],
            },
        )


def test_reason_candidates_with_gateway_returns_ranked_output():
    profile = StudentProfile(total_score=27, subject_combination="A00", preferred_majors=["computer_science"])
    candidates = [
        CandidateProgram(
            candidate_id="hust:1",
            school_id="hust",
            school_name="HUST",
            admission_year=2026,
            program_id="computer_science",
            program_name="Khoa hoc May tinh",
            subject_combinations=["A00"],
            evidence=[Evidence(source_url="https://example.com", school_name="HUST", admission_year=2026, field_name="record")],
        )
    ]

    checks, recommendations = reason_candidates_with_gateway(profile=profile, candidates=candidates, gateway=FakeGateway())

    assert checks[0].candidate_id == "hust:1"
    assert recommendations[0].band == "safe"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/services/test_reasoning_inference_service.py -v`
Expected: FAIL with `ImportError` for `reasoning_inference_service`

- [ ] **Step 3: Write minimal implementation**

```python
# services/reasoning_inference_service.py
import json

from agents.models import EligibilityCheck, RankedRecommendation
from services.inference.models import InferenceRequest


REASONING_SYSTEM_PROMPT = """
Rank admission candidates conservatively.
Return JSON with keys: eligibility_checks and ranked_recommendations.
Bands must be one of: safe, match, reach, unknown.
"""


def reason_candidates_with_gateway(profile, candidates, gateway):
    payload = {
        "profile": profile.model_dump(),
        "candidates": [candidate.model_dump() for candidate in candidates],
    }
    result = gateway.run(
        InferenceRequest(
            agent_name="reasoning_agent",
            task_type="recommendation_reasoning",
            system_prompt=REASONING_SYSTEM_PROMPT.strip(),
            user_prompt=json.dumps(payload, ensure_ascii=False),
            output_mode="json",
            temperature=0.0,
        )
    )
    parsed = result.parsed_data or {}
    checks = [EligibilityCheck(**item) for item in parsed.get("eligibility_checks", [])]
    recommendations = [RankedRecommendation(**item) for item in parsed.get("ranked_recommendations", [])]
    return checks, recommendations
```

```python
# agents/reasoning_agent.py
from services import build_default_gateway
from services.reasoning_inference_service import reason_candidates_with_gateway
from state import AgentState


def reasoning_agent(state: AgentState):
    gateway = build_default_gateway()
    checks, recommendations = reason_candidates_with_gateway(
        profile=state.student_profile,
        candidates=state.retrieved_programs,
        gateway=gateway,
    )
    state.eligibility_checks = checks
    state.ranked_recommendations = recommendations
    return state
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/services/test_reasoning_inference_service.py tests/agents/test_reasoning_agent.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/reasoning_inference_service.py agents/reasoning_agent.py tests/services/test_reasoning_inference_service.py tests/agents/test_reasoning_agent.py
git commit -m "feat: route recommendation reasoning through inference gateway"
```

### Task 3: Migrate Explanation Drafting To Gateway While Keeping Policy Output Deterministic

**Files:**
- Create: `services/explanation_inference_service.py`
- Modify: `agents/explanation_agent.py`
- Modify: `tests/agents/test_explanation_agent.py`
- Test: `tests/services/test_explanation_inference_service.py`

- [ ] **Step 1: Write the failing test**

```python
from services.explanation_inference_service import build_explanation_with_gateway
from services.inference.models import InferenceResult


class FakeGateway:
    def run(self, request):
        return InferenceResult(
            agent_name=request.agent_name,
            model="gemini-2.5-flash-lite",
            provider="fake",
            content="Profile: diem=27\nGoi y chuong trinh phu hop:\n1. Khoa hoc May tinh - HUST [safe, score=0.91]",
        )


def test_build_explanation_with_gateway_returns_text():
    text = build_explanation_with_gateway(
        profile={"total_score": 27},
        recommendations=[{"candidate_id": "hust:1", "band": "safe", "score": 0.91}],
        candidates=[{"candidate_id": "hust:1", "program_name": "Khoa hoc May tinh", "school_name": "HUST"}],
        policy={"warnings": []},
        gateway=FakeGateway(),
    )

    assert "Goi y chuong trinh phu hop" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/services/test_explanation_inference_service.py -v`
Expected: FAIL with `ImportError` for `explanation_inference_service`

- [ ] **Step 3: Write minimal implementation**

```python
# services/explanation_inference_service.py
import json

from services.inference.models import InferenceRequest


EXPLANATION_SYSTEM_PROMPT = """
Write a Vietnamese advisory answer.
Include profile summary, recommended programs, cited sources, warnings, and follow-up needs.
Do not claim guaranteed admission.
"""


def build_explanation_with_gateway(profile, recommendations, candidates, policy, gateway) -> str:
    payload = {
        "profile": profile,
        "recommendations": recommendations,
        "candidates": candidates,
        "policy": policy,
    }
    result = gateway.run(
        InferenceRequest(
            agent_name="explanation_agent",
            task_type="answer_drafting",
            system_prompt=EXPLANATION_SYSTEM_PROMPT.strip(),
            user_prompt=json.dumps(payload, ensure_ascii=False),
            output_mode="free_text",
            temperature=0.2,
        )
    )
    return result.content
```

```python
# agents/explanation_agent.py
from services import build_default_gateway
from services.explanation_inference_service import build_explanation_with_gateway
from state import AgentState


def explanation_agent(state: AgentState):
    gateway = build_default_gateway()
    state.final_answer = build_explanation_with_gateway(
        profile=state.student_profile.model_dump(),
        recommendations=[rec.model_dump() for rec in state.ranked_recommendations],
        candidates=[candidate.model_dump() for candidate in state.retrieved_programs],
        policy=state.policy_decision.model_dump() if state.policy_decision else {},
        gateway=gateway,
    )
    state.advisory = state.final_answer
    state.citations = [ev for program in state.retrieved_programs for ev in program.evidence]
    return state
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/services/test_explanation_inference_service.py tests/agents/test_explanation_agent.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/explanation_inference_service.py agents/explanation_agent.py tests/services/test_explanation_inference_service.py tests/agents/test_explanation_agent.py
git commit -m "feat: route explanation drafting through inference gateway"
```

## Self-Review

Spec coverage in this plan:
- `profile_agent`, `reasoning_agent`, and `explanation_agent` use the shared gateway.
- Retrieval remains deterministic.
- Existing agent boundaries remain intact.

Intentional exclusions from this plan:
- No stronger-model fallback yet.
- No telemetry yet.
- No policy ambiguity escalation yet.

Plan complete and saved to `docs/superpowers/plans/2026-04-26-gemini-backbone-plan-02-advisory-agent-migration.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
