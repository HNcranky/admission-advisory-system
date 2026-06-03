# Slice 3 - Conflict Models and Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Do not create commits for this project unless the user explicitly asks.** Use checkpoint steps instead of `git commit`.

**Goal:** Introduce structured conflict models and deterministic quota-conflict detection without wiring the new conflict node into the graph yet.

**Architecture:** Add `services/conflict/models.py` for `EvidenceOption`, `ConflictRecord`, `ComparisonReport`, and `ResolutionOutcome`. Add `services/conflict/detection.py` to group `CandidateProgram` rows by `(school_id, admission_year, program_id_or_name, admission_method)` and emit one structured conflict per group with distinct quota values. Extend `AgentState` and `CandidateProgram` with the fields later slices need.

**Tech Stack:** Python, Pydantic, pytest.

---

## File Structure

- Create: `services/conflict/__init__.py`
- Create: `services/conflict/models.py`
- Create: `services/conflict/detection.py`
- Modify: `state.py`
- Modify: `agents/models.py`
- Modify: `agents/retrieval_agent.py`
- Create: `tests/services/conflict/__init__.py`
- Create: `tests/services/conflict/test_models.py`
- Create: `tests/services/conflict/test_detection.py`

This slice deliberately removes conflict detection from `retrieval_agent`; after this slice and before Slice 4, conflicts are not surfaced by the graph. That temporary gap is acceptable because `policy_agent` tolerates empty `state.conflicts`.

---

## Task 1: Add Conflict Pydantic Models

**Files:**
- Create: `services/conflict/__init__.py`
- Create: `services/conflict/models.py`
- Create: `tests/services/conflict/__init__.py`
- Create: `tests/services/conflict/test_models.py`

- [ ] **Step 1: Write failing model tests**

Create `tests/services/conflict/__init__.py` as an empty file.

Create `tests/services/conflict/test_models.py`:

```python
from datetime import datetime

from services.conflict.models import (
    ComparisonReport,
    ConflictRecord,
    EvidenceOption,
    ResolutionOutcome,
)


def _option(value=100, trust=2, url="mock://source-a"):
    return EvidenceOption(
        evidence_id=f"{url}|quota",
        source_url=url,
        trust_level=trust,
        fetched_at=datetime(2026, 1, 1),
        confidence_score=0.9,
        value=value,
    )


def test_evidence_option_allows_missing_optional_provenance():
    option = EvidenceOption(evidence_id="x|quota", source_url="mock://x", value=120)

    assert option.trust_level is None
    assert option.fetched_at is None
    assert option.confidence_score is None


def test_conflict_record_carries_conflict_key_and_options():
    record = ConflictRecord(
        conflict_key="vnu_uet:2026:cntt:thpt_score",
        field_name="quota",
        school_id="vnu_uet",
        school_name="Dai hoc Cong nghe - DHQGHN",
        admission_year=2026,
        program_id="cntt",
        program_name="Cong nghe thong tin",
        admission_method="thpt_score",
        options=[_option(120), _option(150)],
    )

    assert record.field_name == "quota"
    assert record.admission_year == 2026
    assert [option.value for option in record.options] == [120, 150]


def test_comparison_report_and_resolution_outcome_shape():
    winning = _option(150, trust=3, url="mock://winner")
    losing = _option(120, trust=2, url="mock://loser")

    report = ComparisonReport(
        ranked_options=[winning, losing],
        is_decisive=True,
        decision_axes=["trust_level"],
    )
    outcome = ResolutionOutcome(
        conflict_key="vnu_uet:2026:cntt:thpt_score",
        field_name="quota",
        school_id="vnu_uet",
        school_name="Dai hoc Cong nghe - DHQGHN",
        program_name="Cong nghe thong tin",
        status="resolved",
        resolved_value=150,
        chosen_evidence=winning,
        rejected_evidence=[losing],
        rationale="Trusted source has higher trust level.",
        decision_axes=report.decision_axes,
    )

    assert outcome.status == "resolved"
    assert outcome.chosen_evidence == winning
    assert outcome.rejected_evidence == [losing]
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
pytest tests/services/conflict/test_models.py -v
```

Expected: FAIL because `services.conflict.models` does not exist.

- [ ] **Step 3: Implement models**

Create `services/conflict/__init__.py` as an empty package marker.

Create `services/conflict/models.py`:

```python
from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field


class EvidenceOption(BaseModel):
    evidence_id: str
    source_url: str
    trust_level: Optional[int] = None
    fetched_at: Optional[datetime] = None
    confidence_score: Optional[float] = None
    value: Any = None


class ConflictRecord(BaseModel):
    conflict_key: str
    field_name: str
    school_id: str
    school_name: str
    admission_year: int
    program_id: Optional[str] = None
    program_name: str
    admission_method: Optional[str] = None
    options: List[EvidenceOption] = Field(default_factory=list)


class ComparisonReport(BaseModel):
    ranked_options: List[EvidenceOption] = Field(default_factory=list)
    is_decisive: bool = False
    decision_axes: List[str] = Field(default_factory=list)


class ResolutionOutcome(BaseModel):
    conflict_key: str
    field_name: str
    school_id: str
    school_name: str
    program_name: str
    status: Literal["resolved", "unresolved"]
    resolved_value: Optional[Any] = None
    chosen_evidence: Optional[EvidenceOption] = None
    rejected_evidence: List[EvidenceOption] = Field(default_factory=list)
    rationale: str
    decision_axes: List[str] = Field(default_factory=list)
    uncertainty_reason: Optional[str] = None
    used_llm_tiebreaker: bool = False
```

- [ ] **Step 4: Run tests**

Run:

```powershell
pytest tests/services/conflict/test_models.py -v
```

Expected: PASS.

---

## Task 2: Extend State and Candidate Models

**Files:**
- Modify: `state.py`
- Modify: `agents/models.py`
- Create: `tests/services/conflict/test_state_extensions.py`

- [ ] **Step 1: Write failing tests for new fields**

Create `tests/services/conflict/test_state_extensions.py`:

```python
from agents.models import CandidateProgram
from services.conflict.models import EvidenceOption, ResolutionOutcome
from state import AgentState


def test_agent_state_has_conflict_record_and_resolution_outcome_lists():
    state = AgentState(user_query="Tu van CNTT")

    assert state.conflict_records == []
    assert state.resolution_outcomes == []


def test_candidate_program_has_data_uncertain_fields():
    candidate = CandidateProgram(
        candidate_id="vnu_uet:2026:cntt:thpt_score",
        school_id="vnu_uet",
        school_name="Dai hoc Cong nghe - DHQGHN",
        admission_year=2026,
        program_id="cntt",
        program_name="Cong nghe thong tin",
    )

    assert candidate.data_uncertain_fields == []


def test_state_accepts_resolution_outcomes():
    option = EvidenceOption(evidence_id="mock://x|quota", source_url="mock://x", value=150)
    outcome = ResolutionOutcome(
        conflict_key="vnu_uet:2026:cntt:thpt_score",
        field_name="quota",
        school_id="vnu_uet",
        school_name="Dai hoc Cong nghe - DHQGHN",
        program_name="Cong nghe thong tin",
        status="resolved",
        resolved_value=150,
        chosen_evidence=option,
        rationale="Higher trust source.",
    )
    state = AgentState(user_query="Tu van CNTT", resolution_outcomes=[outcome])

    assert state.resolution_outcomes[0].resolved_value == 150
```

- [ ] **Step 2: Run and verify failure**

Run:

```powershell
pytest tests/services/conflict/test_state_extensions.py -v
```

Expected: FAIL because fields are missing.

- [ ] **Step 3: Modify `agents/models.py`**

Add to `CandidateProgram`:

```python
    data_uncertain_fields: List[str] = Field(default_factory=list)
```

- [ ] **Step 4: Modify `state.py`**

Add import:

```python
from services.conflict.models import ConflictRecord, ResolutionOutcome
```

Add fields after `conflicts`:

```python
    conflict_records: List[ConflictRecord] = Field(default_factory=list)
    resolution_outcomes: List[ResolutionOutcome] = Field(default_factory=list)
```

- [ ] **Step 5: Run tests**

Run:

```powershell
pytest tests/services/conflict/test_state_extensions.py -v
```

Expected: PASS.

---

## Task 3: Implement Quota Conflict Detection

**Files:**
- Create: `services/conflict/detection.py`
- Create: `tests/services/conflict/test_detection.py`

- [ ] **Step 1: Write failing detection tests**

Create `tests/services/conflict/test_detection.py`:

```python
from agents.models import CandidateProgram, Evidence
from services.conflict.detection import detect_quota_conflicts


def candidate(
    *,
    quota,
    source_url,
    trust=2,
    school_id="vnu_uet",
    year=2026,
    program_id="cntt",
    program_name="Cong nghe thong tin",
    method="thpt_score",
):
    return CandidateProgram(
        candidate_id=f"{school_id}:{year}:{program_id}:{method}",
        school_id=school_id,
        school_name="Dai hoc Cong nghe - DHQGHN",
        admission_year=year,
        program_id=program_id,
        program_name=program_name,
        admission_method=method,
        quota=quota,
        evidence=[
            Evidence(
                source_url=source_url,
                school_name="Dai hoc Cong nghe - DHQGHN",
                admission_year=year,
                field_name="quota",
                normalized_value=quota,
                trust_level=trust,
                confidence_score=0.9,
            )
        ],
    )


def test_detects_single_group_with_distinct_quota_values():
    conflicts = detect_quota_conflicts(
        [
            candidate(quota={"value": 120, "unit": "students"}, source_url="mock://a"),
            candidate(quota={"value": 150, "unit": "students"}, source_url="mock://b"),
        ]
    )

    assert len(conflicts) == 1
    record = conflicts[0]
    assert record.conflict_key == "vnu_uet:2026:cntt:thpt_score"
    assert record.field_name == "quota"
    assert [option.value for option in record.options] == [120, 150]


def test_no_conflict_when_quotas_are_identical():
    conflicts = detect_quota_conflicts(
        [
            candidate(quota={"value": 150, "unit": "students"}, source_url="mock://a"),
            candidate(quota={"value": 150, "unit": "students"}, source_url="mock://b"),
        ]
    )

    assert conflicts == []


def test_preserves_three_options_for_corroboration():
    conflicts = detect_quota_conflicts(
        [
            candidate(quota={"value": 120, "unit": "students"}, source_url="mock://a"),
            candidate(quota={"value": 150, "unit": "students"}, source_url="mock://b"),
            candidate(quota={"value": 150, "unit": "students"}, source_url="mock://c"),
        ]
    )

    assert len(conflicts) == 1
    assert [option.source_url for option in conflicts[0].options] == [
        "mock://a",
        "mock://b",
        "mock://c",
    ]


def test_does_not_cross_contaminate_groups():
    conflicts = detect_quota_conflicts(
        [
            candidate(quota={"value": 120}, source_url="mock://a", program_id="cntt"),
            candidate(quota={"value": 150}, source_url="mock://b", program_id="cntt"),
            candidate(quota={"value": 200}, source_url="mock://c", program_id="ktmt"),
            candidate(quota={"value": 200}, source_url="mock://d", program_id="ktmt"),
        ]
    )

    assert len(conflicts) == 1
    assert conflicts[0].program_id == "cntt"


def test_heterogeneous_quota_shapes_are_conflict_eligible():
    conflicts = detect_quota_conflicts(
        [
            candidate(quota={"value": 150}, source_url="mock://a"),
            candidate(quota={"raw": "150 chi tieu"}, source_url="mock://b"),
        ]
    )

    assert len(conflicts) == 1
```

- [ ] **Step 2: Run and verify failure**

Run:

```powershell
pytest tests/services/conflict/test_detection.py -v
```

Expected: FAIL because `services.conflict.detection` does not exist.

- [ ] **Step 3: Implement detection**

Create `services/conflict/detection.py`:

```python
import json
from collections import defaultdict
from typing import Any, Dict, Hashable, List, Tuple

from agents.models import CandidateProgram
from services.conflict.models import ConflictRecord, EvidenceOption


def _conflict_key(candidate: CandidateProgram) -> Tuple[str, int, str, str]:
    return (
        candidate.school_id,
        candidate.admission_year,
        candidate.program_id or candidate.program_name,
        candidate.admission_method or "unknown_method",
    )


def _conflict_key_text(key: Tuple[str, int, str, str]) -> str:
    return ":".join(str(part) for part in key)


def _normalize_quota_value(quota: Any) -> Hashable:
    if quota is None:
        return ("none", None)
    if isinstance(quota, dict):
        if set(quota.keys()) == {"value"} or {"value", "unit"}.issuperset(quota.keys()):
            return ("value", quota.get("value"), quota.get("unit"))
        return ("json", json.dumps(quota, sort_keys=True, ensure_ascii=False))
    return ("raw", str(quota))


def _option_from_candidate(candidate: CandidateProgram) -> EvidenceOption:
    evidence = candidate.evidence[0] if candidate.evidence else None
    source_url = evidence.source_url if evidence else ""
    value = candidate.quota.get("value") if isinstance(candidate.quota, dict) and "value" in candidate.quota else candidate.quota
    return EvidenceOption(
        evidence_id=f"{source_url}|quota",
        source_url=source_url,
        trust_level=evidence.trust_level if evidence else None,
        confidence_score=evidence.confidence_score if evidence else None,
        value=value,
    )


def detect_quota_conflicts(candidates: List[CandidateProgram]) -> List[ConflictRecord]:
    groups: Dict[Tuple[str, int, str, str], List[CandidateProgram]] = defaultdict(list)
    for candidate in candidates:
        groups[_conflict_key(candidate)].append(candidate)

    records: List[ConflictRecord] = []
    for key, group in groups.items():
        if len(group) < 2:
            continue
        distinct_values = {_normalize_quota_value(candidate.quota) for candidate in group}
        if len(distinct_values) < 2:
            continue
        first = group[0]
        records.append(
            ConflictRecord(
                conflict_key=_conflict_key_text(key),
                field_name="quota",
                school_id=first.school_id,
                school_name=first.school_name,
                admission_year=first.admission_year,
                program_id=first.program_id,
                program_name=first.program_name,
                admission_method=first.admission_method,
                options=[_option_from_candidate(candidate) for candidate in group],
            )
        )
    return records
```

- [ ] **Step 4: Run tests**

Run:

```powershell
pytest tests/services/conflict/test_detection.py -v
```

Expected: PASS.

---

## Task 4: Stop Legacy Retrieval Conflict Detection

**Files:**
- Modify: `agents/retrieval_agent.py`
- Create: `tests/agents/test_retrieval_agent_conflict_transition.py`

- [ ] **Step 1: Write failing transition test**

Create `tests/agents/test_retrieval_agent_conflict_transition.py`:

```python
from agents.models import CandidateProgram, StudentProfile
from agents.retrieval_agent import retrieval_agent
from state import AgentState


def test_retrieval_agent_no_longer_populates_legacy_conflicts(monkeypatch):
    candidate = CandidateProgram(
        candidate_id="vnu_uet:2026:cntt:thpt_score",
        school_id="vnu_uet",
        school_name="Dai hoc Cong nghe - DHQGHN",
        admission_year=2026,
        program_id="cntt",
        program_name="Cong nghe thong tin",
        admission_method="thpt_score",
        quota={"value": 120},
    )

    monkeypatch.setattr("agents.retrieval_agent.fetch_candidates", lambda filters: [candidate])

    state = AgentState(user_query="Tu van", student_profile=StudentProfile())
    output = retrieval_agent(state)

    assert output.retrieved_programs == [candidate]
    assert output.conflicts == []
```

- [ ] **Step 2: Run and verify failure**

Run:

```powershell
pytest tests/agents/test_retrieval_agent_conflict_transition.py -v
```

Expected: FAIL if `retrieval_agent` still calls `detect_conflicts`.

- [ ] **Step 3: Modify `agents/retrieval_agent.py`**

Remove `detect_conflicts` from the import list and remove this line:

```python
    state.conflicts = detect_conflicts(candidates)
```

Keep retrieval error handling unchanged:

```python
    except Exception as exc:
        state.retrieved_programs = []
        state.conflicts = [f"Retrieval error: {exc}"]
        return state
```

- [ ] **Step 4: Run focused tests**

Run:

```powershell
pytest tests/agents/test_retrieval_agent_conflict_transition.py tests/services/conflict/test_detection.py -v
```

Expected: PASS.

---

## Task 5: Slice Verification

**Files:**
- No edits.

- [ ] **Step 1: Run all conflict model/detection tests**

Run:

```powershell
pytest tests/services/conflict/test_models.py tests/services/conflict/test_state_extensions.py tests/services/conflict/test_detection.py tests/agents/test_retrieval_agent_conflict_transition.py -v
```

Expected: PASS.

- [ ] **Step 2: Run broader agent tests**

Run:

```powershell
pytest tests/agents -v
```

Expected: PASS. If tests assume retrieval populates `state.conflicts`, update those tests to reflect the new graph-owned conflict responsibility planned for Slice 4.

- [ ] **Step 3: Check diff, do not commit**

Run:

```powershell
git diff -- services/conflict state.py agents/models.py agents/retrieval_agent.py tests/services/conflict tests/agents/test_retrieval_agent_conflict_transition.py
git status --short
```

Expected: only slice-3 files are modified/created. Do not run `git commit`.
