# Slice 01 — Pydantic v2 migration & dead-code removal

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Remove the two Pydantic v1 deprecation warnings and delete the abandoned LLM-reasoning stub plus its dead test.

**Architecture:** Pure cleanup — no behaviour change. Two independent tasks.

**Tech Stack:** Python 3.12, Pydantic v2, pytest.

**Spec:** `docs/superpowers/specs/2026-05-29-tech-debt-cleanup-design.md` (items C1, C2)

**Depends on:** nothing. **Branch:** `chore/stabilize-cleanup`.

> Test commands use `.venv/Scripts/python.exe -m pytest`. See `README.md` for shared DB setup (not needed for this slice — these tests don't touch the DB).

---

## Task 1: Migrate Pydantic v1 `class Config` to v2 `model_config`

**Files:**
- Modify: `ingestion/registry/models.py:73-74`
- Modify: `ingestion/models/pipeline_models.py:48-50`
- Test: `tests/ingestion/test_pydantic_config_migration.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/ingestion/test_pydantic_config_migration.py`:

```python
from ingestion.registry.models import SourceEntry
from ingestion.models.pipeline_models import FetchResult


def test_source_entry_uses_model_config():
    assert not hasattr(SourceEntry, "Config")
    assert SourceEntry.model_config.get("use_enum_values") is True


def test_fetch_result_uses_model_config():
    assert not hasattr(FetchResult, "Config")
    assert FetchResult.model_config.get("arbitrary_types_allowed") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/ingestion/test_pydantic_config_migration.py -v`
Expected: FAIL — `SourceEntry` still has a `Config` attribute, so `not hasattr(...)` is False.

- [ ] **Step 3: Migrate `ingestion/registry/models.py`**

Ensure `ConfigDict` is imported (add to the existing pydantic import line, e.g. `from pydantic import BaseModel, Field, ConfigDict`). Replace lines 73-74:

```python
    class Config:
        use_enum_values = True
```

with (as a class attribute where the fields end):

```python
    model_config = ConfigDict(use_enum_values=True)
```

- [ ] **Step 4: Migrate `ingestion/models/pipeline_models.py`**

Ensure `ConfigDict` is imported. Replace lines 48-50:

```python
    class Config:

        arbitrary_types_allowed = True
```

with:

```python
    model_config = ConfigDict(arbitrary_types_allowed=True)
```

- [ ] **Step 5: Run the migration test + warning check**

Run: `.venv/Scripts/python.exe -m pytest tests/ingestion/test_pydantic_config_migration.py -v -W error::DeprecationWarning`
Expected: PASS, and no `PydanticDeprecatedSince20` error on import of these modules.

- [ ] **Step 6: Commit**

```bash
git add ingestion/registry/models.py ingestion/models/pipeline_models.py tests/ingestion/test_pydantic_config_migration.py
git commit -m "refactor: migrate Pydantic v1 Config to v2 model_config"
```

---

## Task 2: Delete the abandoned LLM-reasoning stub and its dead test

**Files:**
- Delete: `services/reasoning_inference_service.py`
- Delete: `tests/services/test_reasoning_inference_service.py`

- [ ] **Step 1: Confirm the stub is referenced nowhere in live code**

Run: `git grep -n "reasoning_inference_service"`
Expected: only matches are the empty module file and the commented import in the test file. No live import.

- [ ] **Step 2: Delete both files**

```bash
git rm services/reasoning_inference_service.py tests/services/test_reasoning_inference_service.py
```

- [ ] **Step 3: Run the suite to confirm nothing breaks**

Run: `.venv/Scripts/python.exe -m pytest -m "not integration" -q`
Expected: PASS, no collection/import errors.

- [ ] **Step 4: Commit**

```bash
git commit -m "chore: remove empty reasoning_inference_service stub and dead test"
```
