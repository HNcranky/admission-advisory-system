# Slice 1 - Mock Retrieval Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Do not create commits for this project unless the user explicitly asks.** Use the checkpoint steps instead of `git commit`.

**Goal:** Add `ADVISORY_MOCK_CONFLICTS=1` so retrieval can return stable synthetic conflicting `CandidateProgram` rows without touching Postgres.

**Architecture:** Keep `retrieval_agent` unchanged except for whatever behavior naturally comes from `fetch_candidates`. Add a tiny `services/mock_retrieval.py` module that owns env parsing and synthetic candidate construction. Put the env guard at the very top of `services/retrieval_service.py:fetch_candidates`, before SQL construction and before `get_cursor`.

**Tech Stack:** Python, Pydantic models in `agents.models`, pytest, monkeypatch.

---

## File Structure

- Create: `services/mock_retrieval.py` - env flag helper and deterministic mock candidate builder.
- Modify: `services/retrieval_service.py` - early return from `fetch_candidates` when mock mode is enabled.
- Modify: `.env.example` - document `ADVISORY_MOCK_CONFLICTS=0`.
- Create: `tests/services/test_mock_retrieval.py` - focused tests for env parsing, filter behavior, candidate shape, and no DB access.

This slice intentionally does not create the conflict node. With the current legacy flow, mock retrieval should still allow `retrieval_agent` to populate `state.conflicts` through the existing flat `detect_conflicts` call, which gives a cheap smoke test before later slices replace that path.

---

## Task 1: Add the Mock Retrieval Module

**Files:**
- Create: `services/mock_retrieval.py`
- Test: `tests/services/test_mock_retrieval.py`

- [ ] **Step 1: Write failing tests for env parsing and candidate shape**

Create `tests/services/test_mock_retrieval.py`:

```python
from services.mock_retrieval import (
    build_mock_conflict_candidates,
    mock_conflicts_enabled,
)


def test_mock_conflicts_enabled_defaults_false(monkeypatch):
    monkeypatch.delenv("ADVISORY_MOCK_CONFLICTS", raising=False)
    assert mock_conflicts_enabled() is False


def test_mock_conflicts_enabled_accepts_truthy_values(monkeypatch):
    for value in ["1", "true", "TRUE", "yes", "on"]:
        monkeypatch.setenv("ADVISORY_MOCK_CONFLICTS", value)
        assert mock_conflicts_enabled() is True


def test_mock_conflicts_enabled_rejects_falsey_values(monkeypatch):
    for value in ["", "0", "false", "no", "off", "anything_else"]:
        monkeypatch.setenv("ADVISORY_MOCK_CONFLICTS", value)
        assert mock_conflicts_enabled() is False


def test_mock_candidates_share_conflict_key_and_have_distinct_quotas():
    candidates = build_mock_conflict_candidates(
        filters={"admission_year": 2026},
        limit=100,
    )

    assert len(candidates) == 3
    keys = {
        (
            candidate.school_id,
            candidate.admission_year,
            candidate.program_id,
            candidate.admission_method,
        )
        for candidate in candidates
    }
    assert keys == {("vnu_uet", 2026, "cntt", "thpt_score")}

    quotas = {candidate.quota["value"] for candidate in candidates}
    assert quotas == {120, 150}

    for candidate in candidates:
        assert candidate.metadata["mock_conflict"] is True
        assert candidate.metadata["mock_dataset"] == "advisory_conflict_v1"
        assert candidate.evidence
        assert candidate.evidence[0].source_url.startswith("mock://")
        assert candidate.evidence[0].field_name == "quota"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
pytest tests/services/test_mock_retrieval.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'services.mock_retrieval'`.

- [ ] **Step 3: Implement `services/mock_retrieval.py`**

Create `services/mock_retrieval.py`:

```python
import os
from typing import Any, Dict, List

from agents.models import CandidateProgram, Evidence

MOCK_SCHOOL_ID = "vnu_uet"
MOCK_PROGRAM_ID = "cntt"
MOCK_PROGRAM_NAME = "Cong nghe thong tin"
MOCK_SCHOOL_NAME = "Dai hoc Cong nghe - DHQGHN"
MOCK_METHOD = "thpt_score"
MOCK_DATASET = "advisory_conflict_v1"
TRUTHY_VALUES = {"1", "true", "yes", "on"}


def mock_conflicts_enabled() -> bool:
    return os.getenv("ADVISORY_MOCK_CONFLICTS", "").strip().lower() in TRUTHY_VALUES


def _matches_preferred_schools(filters: Dict[str, Any]) -> bool:
    preferred_schools = filters.get("preferred_schools") or []
    return not preferred_schools or MOCK_SCHOOL_ID in preferred_schools


def _matches_preferred_majors(filters: Dict[str, Any]) -> bool:
    preferred_majors = [str(item).lower() for item in (filters.get("preferred_majors") or [])]
    if not preferred_majors:
        return True
    normalized_name = MOCK_PROGRAM_NAME.lower()
    return any(
        major == MOCK_PROGRAM_ID
        or major.replace("_", " ") in normalized_name
        or major in normalized_name
        for major in preferred_majors
    )


def _candidate(
    *,
    year: int,
    quota_value: int,
    source_url: str,
    trust_level: int,
    confidence_score: float,
) -> CandidateProgram:
    quota = {"value": quota_value, "unit": "students"}
    return CandidateProgram(
        candidate_id=f"{MOCK_SCHOOL_ID}:{year}:{MOCK_PROGRAM_ID}:{MOCK_METHOD}",
        school_id=MOCK_SCHOOL_ID,
        school_name=MOCK_SCHOOL_NAME,
        admission_year=year,
        program_id=MOCK_PROGRAM_ID,
        program_name=MOCK_PROGRAM_NAME,
        admission_method=MOCK_METHOD,
        subject_combinations=["A00", "A01"],
        quota=quota,
        tuition={"value": 32000000, "currency": "VND", "period": "year"},
        metadata={"mock_conflict": True, "mock_dataset": MOCK_DATASET},
        evidence=[
            Evidence(
                source_url=source_url,
                school_name=MOCK_SCHOOL_NAME,
                admission_year=year,
                field_name="quota",
                normalized_value=quota,
                confidence_score=confidence_score,
                trust_level=trust_level,
            )
        ],
    )


def build_mock_conflict_candidates(
    filters: Dict[str, Any],
    limit: int = 100,
) -> List[CandidateProgram]:
    if not _matches_preferred_schools(filters):
        return []
    if not _matches_preferred_majors(filters):
        return []

    year = int(filters.get("admission_year") or 2026)
    candidates = [
        _candidate(
            year=year,
            quota_value=120,
            source_url="mock://uet/program-page",
            trust_level=2,
            confidence_score=0.86,
        ),
        _candidate(
            year=year,
            quota_value=150,
            source_url="mock://vnu/proposal-pdf",
            trust_level=3,
            confidence_score=0.94,
        ),
        _candidate(
            year=year,
            quota_value=150,
            source_url="mock://uet/admission-news",
            trust_level=2,
            confidence_score=0.9,
        ),
    ]
    return candidates[:limit]
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```powershell
pytest tests/services/test_mock_retrieval.py -v
```

Expected: PASS.

---

## Task 2: Wire Mock Mode into `fetch_candidates`

**Files:**
- Modify: `services/retrieval_service.py`
- Test: `tests/services/test_mock_retrieval.py`

- [ ] **Step 1: Add failing tests proving DB is not touched when env is enabled**

Append to `tests/services/test_mock_retrieval.py`:

```python
import services.retrieval_service as retrieval_service


def test_fetch_candidates_uses_mock_without_opening_db(monkeypatch):
    monkeypatch.setenv("ADVISORY_MOCK_CONFLICTS", "1")

    def fail_get_cursor(*args, **kwargs):
        raise AssertionError("DB cursor should not be opened in mock retrieval mode")

    monkeypatch.setattr(retrieval_service, "get_cursor", fail_get_cursor)

    candidates = retrieval_service.fetch_candidates({"admission_year": 2026})

    assert len(candidates) == 3
    assert {candidate.quota["value"] for candidate in candidates} == {120, 150}


def test_fetch_candidates_mock_respects_preferred_school_filter(monkeypatch):
    monkeypatch.setenv("ADVISORY_MOCK_CONFLICTS", "1")

    candidates = retrieval_service.fetch_candidates(
        {"admission_year": 2026, "preferred_schools": ["hust"]}
    )

    assert candidates == []


def test_fetch_candidates_mock_respects_preferred_major_filter(monkeypatch):
    monkeypatch.setenv("ADVISORY_MOCK_CONFLICTS", "1")

    candidates = retrieval_service.fetch_candidates(
        {"admission_year": 2026, "preferred_majors": ["kinh_te"]}
    )

    assert candidates == []


def test_fetch_candidates_mock_allows_matching_major_name(monkeypatch):
    monkeypatch.setenv("ADVISORY_MOCK_CONFLICTS", "1")

    candidates = retrieval_service.fetch_candidates(
        {"admission_year": 2026, "preferred_majors": ["cong_nghe_thong_tin"]}
    )

    assert len(candidates) == 3
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
pytest tests/services/test_mock_retrieval.py -v
```

Expected: at least one FAIL because `fetch_candidates` still opens the DB path.

- [ ] **Step 3: Add the early guard in `services/retrieval_service.py`**

Modify imports near the top:

```python
from services.mock_retrieval import (
    build_mock_conflict_candidates,
    mock_conflicts_enabled,
)
```

Modify the start of `fetch_candidates`:

```python
def fetch_candidates(filters: Dict[str, Any], limit: int = 100) -> List[CandidateProgram]:
    if mock_conflicts_enabled():
        return build_mock_conflict_candidates(filters=filters, limit=limit)

    where_clauses: List[str] = ["admission_year = %s"]
    params: List[Any] = [filters["admission_year"]]
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```powershell
pytest tests/services/test_mock_retrieval.py -v
```

Expected: PASS.

---

## Task 3: Add a Retrieval-Agent Smoke Test

**Files:**
- Modify: `tests/services/test_mock_retrieval.py`

- [ ] **Step 1: Add failing smoke test for legacy conflict surfacing**

Append:

```python
from agents.models import StudentProfile
from agents.retrieval_agent import retrieval_agent
from state import AgentState


def test_retrieval_agent_surfaces_mock_quota_conflict_in_legacy_conflicts(monkeypatch):
    monkeypatch.setenv("ADVISORY_MOCK_CONFLICTS", "1")
    state = AgentState(
        user_query="Tu van CNTT UET",
        student_profile=StudentProfile(
            preferred_schools=["vnu_uet"],
            preferred_majors=["cntt"],
            subject_combination="A00",
        ),
        admission_year=2026,
    )

    output = retrieval_agent(state)

    assert len(output.retrieved_programs) == 3
    assert output.conflicts == [
        "Quota conflict for Cong nghe thong tin at Dai hoc Cong nghe - DHQGHN"
    ]
```

- [ ] **Step 2: Run the smoke test**

Run:

```powershell
pytest tests/services/test_mock_retrieval.py::test_retrieval_agent_surfaces_mock_quota_conflict_in_legacy_conflicts -v
```

Expected: PASS. If this fails with duplicate conflict strings, keep production code unchanged and update `detect_conflicts` only if its current de-duplication is broken.

---

## Task 4: Document the Env Flag

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Add the env var**

Append to `.env.example`:

```dotenv
# Local/test/demo only. When set to 1, retrieval returns in-memory conflicting candidates.
ADVISORY_MOCK_CONFLICTS=0
```

- [ ] **Step 2: Run a quick grep**

Run:

```powershell
rg -n "ADVISORY_MOCK_CONFLICTS" .env.example services tests
```

Expected: matches in `.env.example`, `services/mock_retrieval.py`, `services/retrieval_service.py`, and `tests/services/test_mock_retrieval.py`.

---

## Task 5: Slice Verification

**Files:**
- No edits.

- [ ] **Step 1: Run focused tests**

Run:

```powershell
pytest tests/services/test_mock_retrieval.py -v
```

Expected: PASS.

- [ ] **Step 2: Run advisory smoke tests that could be impacted by retrieval**

Run:

```powershell
pytest tests/e2e/test_advisory_flow.py tests/agents/test_policy_agent.py -v
```

Expected: PASS or existing unrelated skips. If a failure is caused by env leakage, ensure every mock test uses `monkeypatch` and does not modify process env permanently.

- [ ] **Step 3: Check diff, do not commit**

Run:

```powershell
git diff -- services/mock_retrieval.py services/retrieval_service.py tests/services/test_mock_retrieval.py .env.example
git status --short
```

Expected: only the files from this slice are modified/created. Do not run `git commit`.
