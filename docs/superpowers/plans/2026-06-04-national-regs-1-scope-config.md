# National Regulations — Plan 1/3: Scope constants + curated config & loader

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce the national-scope sentinel (`school="MOET"`) and a curated list of official regulation PDF URLs with a loader — the foundation the ingest CLI (Plan 2) and retrieval pass (Plan 3) build on.

**Architecture:** A leaf module `services/knowledge/scope.py` holds the shared constants (`NATIONAL_SCHOOL`, `NATIONAL_DOCUMENT_TYPE`) so both `ingestion/` and `services/chat/` can import them without reversing the existing `ingestion → services` dependency. `local_metadata.KNOWN_SCHOOLS` is extended to include the sentinel (single source of truth). A curated `seeds/national_sources.json` + `national_sources.py` loader supplies the official `datafiles.chinhphu.vn` PDF URLs.

**Tech Stack:** Python 3.12, stdlib `json`/`pathlib`, pytest.

> This refines spec §5.2 (which placed the constants in `local_metadata.py`): the shared sentinel lives in `services/knowledge/scope.py` to avoid a `services → ingestion` import. `KNOWN_SCHOOLS` still lives in `local_metadata.py` and references the constant.

Implements spec sections §5.1 (curated config) and §5.2 (scope constants). Plans 2 and 3 depend on this plan; do this one first.

---

### Task 1: Shared scope constants

**Files:**
- Create: `services/knowledge/scope.py`
- Test: `tests/services/knowledge/test_scope.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/services/knowledge/test_scope.py
from services.knowledge.scope import NATIONAL_SCHOOL, NATIONAL_DOCUMENT_TYPE


def test_national_scope_constants():
    assert NATIONAL_SCHOOL == "MOET"
    assert NATIONAL_DOCUMENT_TYPE == "national_regulation"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/services/knowledge/test_scope.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.knowledge.scope'`

- [ ] **Step 3: Implement the constants module**

```python
# services/knowledge/scope.py
"""National-scope sentinel for knowledge documents that apply to every school
(e.g. Bộ GD&ĐT admission regulations). Kept in a leaf module so both the
ingestion pipeline and the chat fan-out can import it without a cycle."""

# Stored in the `school` column as a sentinel "scope" tag (not a real school).
NATIONAL_SCHOOL = "MOET"

# document_type distinguishing national regulations from per-school PDFs.
NATIONAL_DOCUMENT_TYPE = "national_regulation"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/services/knowledge/test_scope.py -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add services/knowledge/scope.py tests/services/knowledge/test_scope.py
git commit -m "feat: add national-scope sentinel constants (MOET)"
```

---

### Task 2: Register the sentinel in KNOWN_SCHOOLS

**Files:**
- Modify: `ingestion/knowledge/local_metadata.py:18-20`
- Test: `tests/ingestion/knowledge/test_local_metadata.py` (append)

- [ ] **Step 1: Write the failing test (append)**

```python
# append to tests/ingestion/knowledge/test_local_metadata.py
from ingestion.knowledge.local_metadata import KNOWN_SCHOOLS
from services.knowledge.scope import NATIONAL_SCHOOL


def test_national_sentinel_is_a_known_school():
    # MOET is a valid scope tag so storage/vector_search accept it,
    # while the per-school codes remain present.
    assert NATIONAL_SCHOOL in KNOWN_SCHOOLS
    assert {"HUST", "NEU", "VNU-UET"}.issubset(set(KNOWN_SCHOOLS))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_local_metadata.py::test_national_sentinel_is_a_known_school -q`
Expected: FAIL — `assert 'MOET' in ('HUST', 'NEU', 'VNU-UET')`

- [ ] **Step 3: Extend KNOWN_SCHOOLS**

In `ingestion/knowledge/local_metadata.py`, change the import block / constant. The current lines (18-21) are:

```python
# Hard filter in vector_search — MUST stay in sync with the school codes used in
# knowledge_sources.json and the intent router. Anything else maps to "unknown".
KNOWN_SCHOOLS = ("HUST", "NEU", "VNU-UET")
UNKNOWN_SCHOOL = "unknown"
```

Replace them with:

```python
# Hard filter in vector_search — MUST stay in sync with the school codes used in
# knowledge_sources.json and the intent router. Anything else maps to "unknown".
# NATIONAL_SCHOOL ("MOET") is a national-scope sentinel, not a real school: it
# tags Bộ GD&ĐT regulations that apply to every school. It is NOT offered to
# students as a selectable school (the chat picker does not read KNOWN_SCHOOLS).
from services.knowledge.scope import NATIONAL_SCHOOL

KNOWN_SCHOOLS = ("HUST", "NEU", "VNU-UET", NATIONAL_SCHOOL)
UNKNOWN_SCHOOL = "unknown"
```

(Add the `from services.knowledge.scope import NATIONAL_SCHOOL` line with the other top-level imports if your linter prefers; placing it just above the constant is fine and keeps the rationale together. `services.knowledge.scope` is a leaf module, so there is no import cycle.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_local_metadata.py -q`
Expected: PASS (all green — the existing local_metadata tests plus the new one)

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/local_metadata.py tests/ingestion/knowledge/test_local_metadata.py
git commit -m "feat: register MOET national sentinel in KNOWN_SCHOOLS"
```

---

### Task 3: Curated sources file + loader

**Files:**
- Create: `ingestion/knowledge/seeds/national_sources.json`
- Create: `ingestion/knowledge/national_sources.py`
- Test: `tests/ingestion/knowledge/test_national_sources.py`

- [ ] **Step 1: Create the curated seed file**

```json
[
  {
    "url": "https://datafiles.chinhphu.vn/cpp/files/vbpq/2022/08/08-bgddt.signed.pdf",
    "title": "Thông tư 08/2022/TT-BGDĐT — Quy chế tuyển sinh đại học"
  }
]
```

Save as `ingestion/knowledge/seeds/national_sources.json`. To add more documents later: open the document page on `vanban.chinhphu.vn`, copy the attachment link pointing at `datafiles.chinhphu.vn/.../*.signed.pdf`, and append a `{url, title}` row.

- [ ] **Step 2: Write the failing test**

```python
# tests/ingestion/knowledge/test_national_sources.py
import json

from ingestion.knowledge.national_sources import load_national_sources


def test_loads_curated_rows(tmp_path):
    p = tmp_path / "n.json"
    p.write_text(json.dumps([
        {"url": "https://datafiles.chinhphu.vn/a.pdf", "title": "A"},
        {"url": "https://datafiles.chinhphu.vn/b.pdf", "title": "B"},
    ]), encoding="utf-8")
    rows = load_national_sources(p)
    assert [r["url"] for r in rows] == [
        "https://datafiles.chinhphu.vn/a.pdf",
        "https://datafiles.chinhphu.vn/b.pdf",
    ]


def test_skips_rows_without_url(tmp_path):
    p = tmp_path / "n.json"
    p.write_text(json.dumps([
        {"title": "no url"},
        {"url": "https://datafiles.chinhphu.vn/ok.pdf", "title": "ok"},
    ]), encoding="utf-8")
    rows = load_national_sources(p)
    assert [r["url"] for r in rows] == ["https://datafiles.chinhphu.vn/ok.pdf"]


def test_missing_file_returns_empty(tmp_path):
    assert load_national_sources(tmp_path / "nope.json") == []


def test_default_seed_file_is_valid():
    # the committed seed file loads and every row has a url
    rows = load_national_sources()
    assert len(rows) >= 1
    assert all(r.get("url") for r in rows)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_national_sources.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingestion.knowledge.national_sources'`

- [ ] **Step 4: Implement the loader**

```python
# ingestion/knowledge/national_sources.py
"""Curated list of official national admission-regulation PDFs (spec §5.1).

Each row is a {"url", "title"} dict; `url` points at an official
datafiles.chinhphu.vn signed PDF. Ingested under the national scope by
`python -m ingestion.knowledge.ingest_national` (Plan 2)."""
import json
from pathlib import Path

_DEFAULT_SEED = Path(__file__).parent / "seeds" / "national_sources.json"


def load_national_sources(path=None) -> list[dict]:
    """Return curated rows with a non-empty `url`; skip malformed rows.
    A missing file yields []."""
    p = Path(path) if path is not None else _DEFAULT_SEED
    if not p.exists():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    return [r for r in raw if isinstance(r, dict) and r.get("url")]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_national_sources.py -q`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add ingestion/knowledge/seeds/national_sources.json ingestion/knowledge/national_sources.py tests/ingestion/knowledge/test_national_sources.py
git commit -m "feat: add curated national_sources seed + loader"
```

---

## Done when
- `services.knowledge.scope` exposes `NATIONAL_SCHOOL == "MOET"` and `NATIONAL_DOCUMENT_TYPE == "national_regulation"`.
- `KNOWN_SCHOOLS` includes the sentinel without dropping the per-school codes.
- `load_national_sources()` reads the committed seed file (≥1 row) and skips malformed rows.
- All existing tests still pass: `.venv/bin/python -m pytest tests/ingestion/knowledge tests/services/knowledge -q`
