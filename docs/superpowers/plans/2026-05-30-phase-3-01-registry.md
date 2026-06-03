# Phase 3 · Plan 01 — Knowledge Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a validated, taxonomy-enforced registry of unstructured knowledge sources (≥3 schools × ≥2 document types) that the Phase 3 pipeline iterates over.

**Architecture:** A new `ingestion/knowledge/` package with its own `registry/` subpackage — a Pydantic `KnowledgeSource` model with strict taxonomy validators, a JSON seed file, and a `KnowledgeRegistry` loader. Fully isolated from the admission `ingestion/registry/`; no DB, pure data + validation.

**Tech Stack:** Python, Pydantic v2, pytest.

**Spec:** [`2026-05-30-phase-3-data-collection-design.md`](../specs/2026-05-30-phase-3-data-collection-design.md) §2.

---

### Task 1: Package skeleton

**Files:**
- Create: `ingestion/knowledge/__init__.py`
- Create: `ingestion/knowledge/registry/__init__.py`

- [ ] **Step 1: Create empty package files**

Both files are empty (package markers).

`ingestion/knowledge/__init__.py`:
```python
```

`ingestion/knowledge/registry/__init__.py`:
```python
```

- [ ] **Step 2: Verify they import**

Run: `python -c "import ingestion.knowledge.registry"`
Expected: no output, exit 0.

- [ ] **Step 3: Commit**

```bash
git add ingestion/knowledge/__init__.py ingestion/knowledge/registry/__init__.py
git commit -m "chore(knowledge): add ingestion/knowledge package skeleton"
```

---

### Task 2: `KnowledgeSource` model with taxonomy validation

**Files:**
- Create: `ingestion/knowledge/registry/models.py`
- Test: `tests/ingestion/knowledge/test_models.py`

- [ ] **Step 1: Write the failing test**

`tests/ingestion/knowledge/test_models.py`:
```python
import pytest
from pydantic import ValidationError

from ingestion.knowledge.registry.models import (
    KnowledgeSource,
    KNOWLEDGE_TOPICS,
    KNOWLEDGE_DOCUMENT_TYPES,
)


def test_taxonomy_sets_match_spec():
    assert KNOWLEDGE_TOPICS == {
        "tuition", "curriculum", "scholarship", "dormitory",
        "career", "admission_policy", "program_overview",
    }
    assert "tuition_page" in KNOWLEDGE_DOCUMENT_TYPES
    assert "curriculum_pdf" in KNOWLEDGE_DOCUMENT_TYPES


def test_valid_source_parses_with_defaults():
    s = KnowledgeSource(
        school="HUST",
        source_url="https://example.edu/tuition",
        document_type="tuition_page",
        topic="tuition",
    )
    assert s.fetch_strategy == "http"
    assert s.active is True
    assert s.program is None
    assert s.year is None


def test_invalid_topic_rejected():
    with pytest.raises(ValidationError):
        KnowledgeSource(
            school="HUST",
            source_url="https://example.edu/x",
            document_type="tuition_page",
            topic="weather",          # not in taxonomy
        )


def test_invalid_document_type_rejected():
    with pytest.raises(ValidationError):
        KnowledgeSource(
            school="HUST",
            source_url="https://example.edu/x",
            document_type="random_page",   # not in taxonomy
            topic="tuition",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ingestion/knowledge/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingestion.knowledge.registry.models'`.

- [ ] **Step 3: Write minimal implementation**

`ingestion/knowledge/registry/models.py`:
```python
from pydantic import BaseModel, field_validator

KNOWLEDGE_TOPICS = {
    "tuition",
    "curriculum",
    "scholarship",
    "dormitory",
    "career",
    "admission_policy",
    "program_overview",
}

KNOWLEDGE_DOCUMENT_TYPES = {
    "tuition_page",
    "curriculum_pdf",
    "scholarship_policy",
    "faq",
    "handbook",
    "program_overview_page",
    "career_page",
    "dormitory_page",
}


class KnowledgeSource(BaseModel):
    school: str
    source_url: str
    document_type: str
    topic: str
    fetch_strategy: str = "http"
    program: str | None = None
    year: int | None = None
    active: bool = True

    @field_validator("topic")
    @classmethod
    def _topic_in_taxonomy(cls, v: str) -> str:
        if v not in KNOWLEDGE_TOPICS:
            raise ValueError(
                f"topic {v!r} not in taxonomy {sorted(KNOWLEDGE_TOPICS)}"
            )
        return v

    @field_validator("document_type")
    @classmethod
    def _doctype_in_taxonomy(cls, v: str) -> str:
        if v not in KNOWLEDGE_DOCUMENT_TYPES:
            raise ValueError(
                f"document_type {v!r} not in taxonomy "
                f"{sorted(KNOWLEDGE_DOCUMENT_TYPES)}"
            )
        return v
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ingestion/knowledge/test_models.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/registry/models.py tests/ingestion/knowledge/test_models.py
git commit -m "feat(knowledge): add KnowledgeSource model with taxonomy validation"
```

---

### Task 3: Seed file — 3 schools × ≥2 document types

**Files:**
- Create: `ingestion/knowledge/registry/seeds/knowledge_sources.json`

- [ ] **Step 1: Write the seed file**

`ingestion/knowledge/registry/seeds/knowledge_sources.json`:
```json
[
  {
    "school": "HUST",
    "source_url": "https://ts.hust.edu.vn/hoc-phi",
    "document_type": "tuition_page",
    "topic": "tuition"
  },
  {
    "school": "HUST",
    "source_url": "https://ts.hust.edu.vn/hoc-bong",
    "document_type": "scholarship_policy",
    "topic": "scholarship"
  },
  {
    "school": "NEU",
    "source_url": "https://tuyensinh.neu.edu.vn/hoc-phi",
    "document_type": "tuition_page",
    "topic": "tuition"
  },
  {
    "school": "NEU",
    "source_url": "https://tuyensinh.neu.edu.vn/chuong-trinh-dao-tao",
    "document_type": "program_overview_page",
    "topic": "program_overview"
  },
  {
    "school": "VNU-UET",
    "source_url": "https://uet.vnu.edu.vn/hoc-phi/",
    "document_type": "tuition_page",
    "topic": "tuition"
  },
  {
    "school": "VNU-UET",
    "source_url": "https://uet.vnu.edu.vn/hoc-bong/",
    "document_type": "scholarship_policy",
    "topic": "scholarship"
  }
]
```

- [ ] **Step 2: Verify it is valid JSON**

Run: `python -c "import json; d=json.load(open('ingestion/knowledge/registry/seeds/knowledge_sources.json', encoding='utf-8')); print(len(d), 'entries')"`
Expected: `6 entries`

- [ ] **Step 3: Commit**

```bash
git add ingestion/knowledge/registry/seeds/knowledge_sources.json
git commit -m "feat(knowledge): seed knowledge sources for HUST, NEU, VNU-UET"
```

> **Note for executor:** these URLs are best-effort and MUST be confirmed reachable during Plan 05 (the pipeline has a live-fetch smoke step). If a URL 404s, replace it with the correct official page for the same `document_type`/`topic`. The registry structure does not depend on URLs resolving — unit tests below use this file as-is.

---

### Task 4: `KnowledgeRegistry` loader

**Files:**
- Create: `ingestion/knowledge/registry/knowledge_registry.py`
- Test: `tests/ingestion/knowledge/test_registry.py`

- [ ] **Step 1: Write the failing test**

`tests/ingestion/knowledge/test_registry.py`:
```python
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ingestion.knowledge.registry.knowledge_registry import KnowledgeRegistry


def test_default_seed_loads_three_schools_each_with_two_doc_types():
    reg = KnowledgeRegistry()
    schools = reg.schools()
    assert set(schools) >= {"HUST", "NEU", "VNU-UET"}
    for school in ("HUST", "NEU", "VNU-UET"):
        sources = reg.get_sources_by_school(school)
        doc_types = {s.document_type for s in sources}
        assert len(doc_types) >= 2, f"{school} has < 2 document_types"


def test_all_sources_returns_models():
    reg = KnowledgeRegistry()
    sources = reg.all_sources()
    assert len(sources) >= 6
    assert sources[0].topic in {
        "tuition", "curriculum", "scholarship", "dormitory",
        "career", "admission_policy", "program_overview",
    }


def test_custom_seed_path(tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps([
        {"school": "X", "source_url": "https://x/t",
         "document_type": "tuition_page", "topic": "tuition"},
    ]), encoding="utf-8")
    reg = KnowledgeRegistry(seed_path=seed)
    assert reg.schools() == ["X"]


def test_invalid_entry_in_seed_raises(tmp_path):
    seed = tmp_path / "bad.json"
    seed.write_text(json.dumps([
        {"school": "X", "source_url": "https://x/t",
         "document_type": "tuition_page", "topic": "BOGUS"},
    ]), encoding="utf-8")
    with pytest.raises(ValidationError):
        KnowledgeRegistry(seed_path=seed)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ingestion/knowledge/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingestion.knowledge.registry.knowledge_registry'`.

- [ ] **Step 3: Write minimal implementation**

`ingestion/knowledge/registry/knowledge_registry.py`:
```python
import json
from pathlib import Path

from ingestion.knowledge.registry.models import KnowledgeSource

_DEFAULT_SEED = Path(__file__).parent / "seeds" / "knowledge_sources.json"


class KnowledgeRegistry:
    def __init__(self, seed_path: Path | None = None):
        path = seed_path or _DEFAULT_SEED
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        # Validation (incl. taxonomy) happens here — a bad entry raises.
        self._sources = [KnowledgeSource(**entry) for entry in raw]

    def all_sources(self) -> list[KnowledgeSource]:
        return list(self._sources)

    def get_sources_by_school(self, school: str) -> list[KnowledgeSource]:
        return [s for s in self._sources if s.school == school and s.active]

    def schools(self) -> list[str]:
        seen: list[str] = []
        for s in self._sources:
            if s.school not in seen:
                seen.append(s.school)
        return seen
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ingestion/knowledge/test_registry.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/registry/knowledge_registry.py tests/ingestion/knowledge/test_registry.py
git commit -m "feat(knowledge): add KnowledgeRegistry seed loader"
```

---

### Task 5: Plan-level verification

- [ ] **Step 1: Run the full plan test suite**

Run: `pytest tests/ingestion/knowledge/test_models.py tests/ingestion/knowledge/test_registry.py -v`
Expected: PASS (8 passed).

- [ ] **Step 2: Confirm admission registry untouched**

Run: `git diff --name-only HEAD~4 -- ingestion/registry`
Expected: empty output (no admission registry files changed).

## Deliverable

`KnowledgeRegistry().all_sources()` returns validated `KnowledgeSource` objects for HUST, NEU, VNU-UET (≥2 document_types each), with taxonomy enforced at load time. **Consumed by Plan 05 (pipeline).**
