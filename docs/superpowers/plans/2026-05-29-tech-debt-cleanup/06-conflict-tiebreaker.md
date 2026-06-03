# Slice 06 — Activate the LLM conflict tiebreaker

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Reach the dormant LLM-tiebreaker branch in `resolve()`. When deterministic comparison is not decisive, an LLM picks the most trustworthy source; low-confidence or failing calls still fall back to `unresolved` (current behaviour).

**Architecture:** New adapter `services/conflict/resolution_inference_service.py` (mirrors `policy_inference_service.py`). `conflict_agent` builds the gateway once when conflicts exist and passes a closure into `resolve()`. `resolve()` itself is unchanged — it already accepts a `gateway` callable, guards it, and gates on `confidence == "high"`.

**Tech Stack:** Python 3.12, pytest.

**Spec:** `docs/superpowers/specs/2026-05-29-tech-debt-cleanup-design.md` (item A4)

**Depends on:** Slice 03 (`InferenceError`) and Slice 04 (degradation guards). **Branch:** `chore/stabilize-cleanup`.

---

## Task 1: Create the tiebreaker adapter service

**Files:**
- Create: `services/conflict/resolution_inference_service.py`
- Test: `tests/services/conflict/test_resolution_inference_service.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/services/conflict/test_resolution_inference_service.py`:

```python
from services.conflict.models import ComparisonReport, ConflictRecord, EvidenceOption
from services.conflict.resolution_inference_service import interpret_conflict_tiebreak
from services.inference.models import InferenceError, InferenceResult


def _record():
    return ConflictRecord(
        conflict_key="hust:2026:cs:thpt",
        field_name="quota",
        school_id="hust",
        school_name="HUST",
        admission_year=2026,
        program_name="Khoa hoc May tinh",
    )


def _report():
    return ComparisonReport(
        ranked_options=[
            EvidenceOption(evidence_id="a", source_url="https://a.test", trust_level=5, value=120),
            EvidenceOption(evidence_id="b", source_url="https://b.test", trust_level=3, value=150),
        ],
        is_decisive=False,
    )


class _Gateway:
    def __init__(self, parsed=None, exc=None):
        self._parsed = parsed
        self._exc = exc

    def is_available(self):
        return True

    def run(self, request):
        assert request.agent_name == "resolution_agent"
        assert request.output_mode == "json"
        if self._exc is not None:
            raise self._exc
        return InferenceResult(
            agent_name="resolution_agent", model="m", provider="fake",
            content="{}", parsed_data=self._parsed,
        )


def test_returns_parsed_data():
    gateway = _Gateway(parsed={"confidence": "high", "chosen_source_url": "https://a.test", "rationale": "r"})
    out = interpret_conflict_tiebreak(_record(), _report(), gateway)
    assert out["confidence"] == "high"
    assert out["chosen_source_url"] == "https://a.test"


def test_degrades_on_inference_error():
    gateway = _Gateway(exc=InferenceError("boom"))
    out = interpret_conflict_tiebreak(_record(), _report(), gateway)
    assert out == {"confidence": "low"}


def test_degrades_when_gateway_unavailable():
    class _Unavailable:
        def is_available(self):
            return False

        def run(self, request):
            raise AssertionError("should not be called")

    out = interpret_conflict_tiebreak(_record(), _report(), _Unavailable())
    assert out == {"confidence": "low"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/services/conflict/test_resolution_inference_service.py -v`
Expected: FAIL — module `resolution_inference_service` does not exist.

- [ ] **Step 3: Create the adapter service**

Create `services/conflict/resolution_inference_service.py`:

```python
import json

from services.inference.models import InferenceError, InferenceRequest

RESOLUTION_SYSTEM_PROMPT = """
You are resolving a conflict between admission-data sources for the same program field.
Choose the single most trustworthy source. Prefer higher trust_level, more recent
fetched_at, and higher confidence_score. Never invent a value.
Return JSON with exactly these keys:
- confidence: "high" or "low"
- chosen_source_url: the source_url of the option you trust most
- rationale: one short Vietnamese sentence explaining the choice
Use "high" only when one source is clearly more trustworthy than the others.
""".strip()


def _serialize_option(option):
    return {
        "source_url": option.source_url,
        "trust_level": option.trust_level,
        "fetched_at": option.fetched_at.isoformat() if option.fetched_at else None,
        "confidence_score": option.confidence_score,
        "value": option.value,
    }


def interpret_conflict_tiebreak(record, report, gateway) -> dict:
    default = {"confidence": "low"}
    if hasattr(gateway, "is_available") and not gateway.is_available():
        return default

    payload = {
        "field_name": record.field_name,
        "school_name": record.school_name,
        "program_name": record.program_name,
        "admission_year": record.admission_year,
        "options": [_serialize_option(option) for option in report.ranked_options],
    }
    try:
        result = gateway.run(
            InferenceRequest(
                agent_name="resolution_agent",
                task_type="conflict_tiebreak",
                system_prompt=RESOLUTION_SYSTEM_PROMPT,
                user_prompt=json.dumps(payload, ensure_ascii=False, default=str),
                output_mode="json",
                temperature=0.0,
            )
        )
    except InferenceError:
        return default
    return result.parsed_data or default
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/services/conflict/test_resolution_inference_service.py -v`
Expected: PASS (all three tests).

- [ ] **Step 5: Commit**

```bash
git add services/conflict/resolution_inference_service.py tests/services/conflict/test_resolution_inference_service.py
git commit -m "feat: add LLM conflict tiebreaker adapter service"
```

---

## Task 2: Inject the gateway into `conflict_agent`

**Files:**
- Modify: `agents/conflict_agent.py`
- Test: `tests/agents/test_conflict_agent.py` (add an activation test)

- [ ] **Step 1: Write the failing activation test**

Append to `tests/agents/test_conflict_agent.py`:

```python
import agents.conflict_agent as conflict_agent_module
from agents.conflict_agent import conflict_agent
from agents.models import CandidateProgram, Evidence
from state import AgentState


def _conflicting_state():
    """Two sources disagree on quota for the same program/method (non-decisive tie)."""
    def candidate(evidence_id, quota, trust):
        return CandidateProgram(
            school_id="hust",
            school_name="HUST",
            admission_year=2026,
            program_id="computer_science",
            program_name="Khoa hoc May tinh",
            admission_method="thpt_score",
            quota={"value": quota},
            evidence=[
                Evidence(
                    source_url=f"https://src-{evidence_id}.test",
                    school_name="HUST",
                    admission_year=2026,
                    field_name="quota",
                    trust_level=trust,
                )
            ],
        )

    # Same trust_level on both -> deterministic comparison is NOT decisive.
    return AgentState(
        user_query="q",
        retrieved_programs=[candidate("a", 120, 5), candidate("b", 150, 5)],
    )


def test_conflict_agent_resolves_via_llm_tiebreaker(monkeypatch):
    class _Gateway:
        def is_available(self):
            return True

    monkeypatch.setattr(conflict_agent_module, "build_default_gateway", lambda: _Gateway())

    def fake_tiebreak(record, report, gateway):
        chosen = report.ranked_options[0].source_url
        return {"confidence": "high", "chosen_source_url": chosen, "rationale": "nguon dang tin nhat"}

    monkeypatch.setattr(conflict_agent_module, "interpret_conflict_tiebreak", fake_tiebreak)

    state = conflict_agent(_conflicting_state())

    assert any(o.used_llm_tiebreaker and o.status == "resolved" for o in state.resolution_outcomes)
```

> NOTE: The tiebreaker only fires when `report.is_decisive` is False. If `compare()` rules already make this fixture decisive (it shouldn't, since both options share `trust_level=5` with no other distinguishing axis), tune the fixture so the two options tie on every axis (same `trust_level`, same/absent `fetched_at`, same `confidence_score`). A quick scratch assertion `assert compare(report_options).is_decisive is False` can confirm before wiring.

- [ ] **Step 2: Run the activation test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/agents/test_conflict_agent.py::test_conflict_agent_resolves_via_llm_tiebreaker -v`
Expected: FAIL — `conflict_agent` does not reference `build_default_gateway`/`interpret_conflict_tiebreak`, so no outcome has `used_llm_tiebreaker=True`.

- [ ] **Step 3: Wire the gateway into `conflict_agent`**

In `agents/conflict_agent.py`, add these imports at the top:

```python
from services import build_default_gateway
from services.conflict.resolution_inference_service import interpret_conflict_tiebreak
```

Replace the start of `conflict_agent` (lines 22-31) so it builds the gateway once and passes a closure to `resolve()`:

```python
def conflict_agent(state: AgentState):
    records = detect_quota_conflicts(state.retrieved_programs)
    outcomes = []

    gateway = build_default_gateway() if records else None
    tiebreak = (
        (lambda record, report: interpret_conflict_tiebreak(record, report, gateway))
        if gateway is not None
        else None
    )

    for record in records:
        options = package_evidence(record, state.retrieved_programs)
        record.options = options
        report = compare(options)
        outcome = resolve(record, report, gateway=tiebreak)
        outcomes.append(outcome)
        if outcome.status == "unresolved":
            _mark_uncertain(state, record.conflict_key, record.field_name)
```

(The remainder of the function — setting `state.conflict_records`, `state.resolution_outcomes`, `state.conflicts`, and `return state` — is unchanged.)

- [ ] **Step 4: Run the activation test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/agents/test_conflict_agent.py -v`
Expected: PASS (new test + existing conflict-agent tests still green).

- [ ] **Step 5: Run the full conflict + e2e suites for regressions**

Run: `.venv/Scripts/python.exe -m pytest tests/services/conflict tests/agents tests/e2e/test_real_conflict_resolution.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agents/conflict_agent.py tests/agents/test_conflict_agent.py
git commit -m "feat: activate LLM tiebreaker for non-decisive conflicts"
```

---

## After this slice

Return to `README.md` and run the **Final verification** section (full suite with DB up, then open the PR).
