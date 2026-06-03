# Slice 5 - Real E2E and Docs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Do not create commits for this project unless the user explicitly asks.** Use checkpoint steps instead of `git commit`.

**Goal:** Add opt-in real-data end-to-end validation and user-facing docs for both mock demos and real dataset phase completion.

**Architecture:** Keep default `pytest` fast and DB-independent. Add a `requires_real_dataset` marker for tests that need a reachable Postgres instance and the curated SQL dump. Extend chat/e2e coverage to assert the final assistant answer contains the deterministic `Xac minh du lieu` section.

**Tech Stack:** pytest markers, existing chat/conversation service, Postgres fixture/dump workflow, Markdown docs.

---

## File Structure

- Modify: `pyproject.toml` - add `requires_real_dataset` marker.
- Create: `tests/e2e/test_real_conflict_resolution.py` - skipped unless real dataset env is available.
- Modify: `tests/services/chat/test_run_dispatcher.py` - add mock-style assistant-result assertion at the chat dispatch boundary.
- Modify: `QUICKSTART.md` - document mock demo and real-data completion commands.
- Create/update after Slice 2 acceptance: `tests/e2e/fixtures/real_dataset_dump.sql` - real data dump used by `requires_real_dataset`.

---

## Task 1: Register the Real Dataset Marker

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add marker**

Update `[tool.pytest.ini_options]` markers:

```toml
markers = [
    "integration: tests that require a live Postgres database",
    "requires_real_dataset: tests that require the curated real conflict dataset",
]
```

- [ ] **Step 2: Verify pytest recognizes marker**

Run:

```powershell
pytest --markers | Select-String "requires_real_dataset"
```

Expected: output includes `requires_real_dataset`.

---

## Task 2: Add Real Dataset E2E Test

**Files:**
- Create: `tests/e2e/test_real_conflict_resolution.py`

- [ ] **Step 1: Write the real-data test**

Create `tests/e2e/test_real_conflict_resolution.py`:

```python
import os
from pathlib import Path

import pytest


pytestmark = pytest.mark.requires_real_dataset

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "real_dataset_dump.sql"


def _real_dataset_available() -> bool:
    return bool(os.getenv("DATABASE_URL")) and FIXTURE_PATH.exists()


@pytest.mark.skipif(
    not _real_dataset_available(),
    reason="DATABASE_URL and tests/e2e/fixtures/real_dataset_dump.sql are required",
)
def test_real_conflict_resolution_reaches_final_answer(monkeypatch):
    monkeypatch.delenv("ADVISORY_MOCK_CONFLICTS", raising=False)

    from graph import graph
    from state import AgentState

    result = graph.invoke(
        AgentState(user_query="Tu van nganh Cong nghe thong tin UET nam 2026").dict()
    )

    assert result.get("resolution_outcomes")
    assert result.get("final_answer")
    assert "Xac minh du lieu" in result["final_answer"]
```

If existing e2e tests use `ConversationService` instead of direct graph invocation, adapt the execution call to match the existing pattern, but keep the assertions: `resolution_outcomes` exists and `final_answer` contains verification text.

- [ ] **Step 2: Run without real dataset and verify skip**

Run:

```powershell
pytest tests/e2e/test_real_conflict_resolution.py -v
```

Expected: SKIPPED when `DATABASE_URL` or the fixture dump is absent.

- [ ] **Step 3: Run with real dataset when available**

After Slice 2 has produced and loaded the fixture:

```powershell
pytest -m requires_real_dataset -v
```

Expected: PASS. If it fails because Query B produces no conflicts, do not weaken the test; return to real-data curation.

---

## Task 3: Add Mock Chat Dispatch Surface Test

**Files:**
- Modify: `tests/services/chat/test_run_dispatcher.py`

- [ ] **Step 1: Add a concrete chat dispatch test**

Append to `tests/services/chat/test_run_dispatcher.py`:

```python
def test_dispatcher_posts_mock_conflict_verification_result_message(monkeypatch):
    monkeypatch.setenv("ADVISORY_MOCK_CONFLICTS", "1")
    repo = FakeRepository()
    dispatcher = RunDispatcher(
        repository=repo,
        runner=lambda profile_state, latest_user_message: {
            "final_answer": "Goi y CNTT\n\n## Xac minh du lieu\n- Han ngach co mau thuan."
        },
        executor=InlineExecutor(),
    )

    dispatcher.submit(
        session_token="session-456",
        run_id=8,
        latest_user_message="Tu van nganh Cong nghe thong tin UET nam 2026",
        profile_state=ChatProfileState(
            admission_year=2026,
            total_score=27.0,
            preferred_majors=["cntt"],
            preferred_schools=["vnu_uet"],
        ),
    )

    assert repo.completed[2].count("Xac minh du lieu") == 1
    assert repo.messages[-1] == (
        "session-456",
        "assistant",
        "assistant_result",
        repo.completed[2],
    )
```

- [ ] **Step 2: Run the chat dispatch test**

Run:

```powershell
pytest tests/services/chat/test_run_dispatcher.py -k verification -v
```

Expected: PASS.

---

## Task 4: Document Mock Demo and Real Completion Gates

**Files:**
- Modify: `QUICKSTART.md`

- [ ] **Step 1: Add a conflict-aware demo section**

Append or update a section in `QUICKSTART.md` with this text:

````markdown
### Conflict-aware advisory demo

For a stable local demo that does not require Postgres conflict rows:

```powershell
$env:ADVISORY_MOCK_CONFLICTS="1"
pytest tests/e2e/test_advisory_flow.py -k mock -v
```

The mock mode returns in-memory `CandidateProgram` rows with conflicting quota values. It is only for local development, automated tests, and fallback demos. Do not use it as evidence that the real-data dataset is complete.

For phase completion against real ingested data:

```powershell
pytest -m requires_real_dataset -v
```

This requires a reachable Postgres database and `tests/e2e/fixtures/real_dataset_dump.sql` exported from accepted HUST/VNU-UET ingestion. The real-data test is the thesis/demo-prep gate; mock mode does not replace it.
````

- [ ] **Step 2: Verify docs mention both paths**

Run:

```powershell
rg -n "ADVISORY_MOCK_CONFLICTS|requires_real_dataset|Conflict-aware advisory demo" QUICKSTART.md pyproject.toml tests/e2e
```

Expected: matches in `QUICKSTART.md`, `pyproject.toml`, and relevant tests.

---

## Task 5: Final Verification

**Files:**
- No edits.

- [ ] **Step 1: Run default tests**

Run:

```powershell
pytest -v
```

Expected: PASS, with `requires_real_dataset` tests skipped unless explicitly selected/available.

- [ ] **Step 2: Run mock conflict demo test**

Run:

```powershell
$env:ADVISORY_MOCK_CONFLICTS="1"
pytest tests/e2e/test_advisory_flow.py -k mock -v
Remove-Item Env:\ADVISORY_MOCK_CONFLICTS
```

Expected: PASS and no DB dependency for retrieval.

- [ ] **Step 3: Run real dataset gate when available**

Run:

```powershell
pytest -m requires_real_dataset -v
```

Expected: PASS when the curated dump and DB are present; SKIP only if the environment is not configured. For phase completion, SKIP is not sufficient.

- [ ] **Step 4: Check diff, do not commit**

Run:

```powershell
git diff -- pyproject.toml QUICKSTART.md tests/e2e
git status --short
```

Expected: only slice-5 files are modified/created. Do not run `git commit`.
