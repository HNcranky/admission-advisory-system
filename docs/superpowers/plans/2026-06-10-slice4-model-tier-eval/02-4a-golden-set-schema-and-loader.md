# Plan 02 — 4a: Golden-set schema and loader

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Define the versioned golden-set data model (questions + **frozen**
retrieved chunks + expected grounding) and a JSON loader, plus a small seed
fixture demonstrating the schema. Full curation (≥30 cases) is Plan 05.

**Architecture:** A top-level `eval/knowledge_qa/` package (kept out of the
pytest test paths — later plans add live-LLM code). Pydantic models mirror the
shapes the runner needs: each case carries its retrieved chunks snapshotted at
curation time, so the eval never touches the DB. A `GoldenChunk` converts to the
existing `ScoredChunk` the QA service consumes.

**Tech Stack:** Python, Pydantic v2, pytest.

---

### Task 1: Package skeleton + golden-set models

**Files:**
- Create: `eval/__init__.py`
- Create: `eval/knowledge_qa/__init__.py`
- Create: `eval/knowledge_qa/models.py`
- Create: `tests/eval/__init__.py`
- Create: `tests/eval/knowledge_qa/__init__.py`
- Test: `tests/eval/knowledge_qa/test_models.py`

- [ ] **Step 1: Create the empty package markers**

Create `eval/__init__.py`, `eval/knowledge_qa/__init__.py`,
`tests/eval/__init__.py`, `tests/eval/knowledge_qa/__init__.py` — each an empty
file.

- [ ] **Step 2: Write the failing test `tests/eval/knowledge_qa/test_models.py`**

```python
from eval.knowledge_qa.models import GoldenCase, GoldenChunk
from services.knowledge.models import ScoredChunk


def test_golden_chunk_converts_to_scored_chunk():
    gc = GoldenChunk(
        chunk_text="Chỉ tiêu ngành CNTT năm 2026 là 200.",
        score=0.81,
        school="hust",
        topic="quota",
        source_url="https://hust.edu.vn/ts2026",
    )

    scored = gc.to_scored_chunk()

    assert isinstance(scored, ScoredChunk)
    assert scored.score == 0.81
    assert scored.chunk_text.startswith("Chỉ tiêu")
    assert scored.school == "hust"
    assert scored.source_url == "https://hust.edu.vn/ts2026"


def test_golden_case_defaults_and_abstain():
    case = GoldenCase(
        id="hust-quota-1",
        question="Chỉ tiêu ngành CNTT?",
        school="hust",
        topic="quota",
        chunks=[GoldenChunk(chunk_text="...", score=0.4, school="hust")],
        abstain=True,
    )

    assert case.expected_answer_points == []
    assert case.expected_source_ids == []
    assert case.abstain is True
```

- [ ] **Step 3: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/eval/knowledge_qa/test_models.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'eval.knowledge_qa.models'`.

- [ ] **Step 4: Implement `eval/knowledge_qa/models.py`**

```python
from pydantic import BaseModel, Field

from services.knowledge.models import ScoredChunk


class GoldenChunk(BaseModel):
    """A retrieved chunk frozen into the golden set at curation time. Only the
    fields generation actually reads are required; the rest mirror ScoredChunk."""

    chunk_text: str
    score: float
    school: str
    topic: str | None = None
    source_url: str | None = None

    def to_scored_chunk(self) -> ScoredChunk:
        return ScoredChunk(
            chunk_text=self.chunk_text,
            score=self.score,
            school=self.school,
            topic=self.topic,
            source_url=self.source_url,
        )


class GoldenCase(BaseModel):
    """One eval case. `chunks` is the frozen retrieval substrate; the eval feeds
    them straight into generation for each model under test."""

    id: str
    question: str
    school: str | None = None
    topic: str | None = None
    chunks: list[GoldenChunk]
    # The facts a correct answer must contain (empty for abstain cases).
    expected_answer_points: list[str] = Field(default_factory=list)
    # 1-based indices into `chunks` a faithful answer should cite.
    expected_source_ids: list[int] = Field(default_factory=list)
    # True when the chunks lack the info and the model SHOULD return no answer.
    abstain: bool = False
```

- [ ] **Step 5: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/eval/knowledge_qa/test_models.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add eval/__init__.py eval/knowledge_qa/__init__.py eval/knowledge_qa/models.py \
  tests/eval/__init__.py tests/eval/knowledge_qa/__init__.py \
  tests/eval/knowledge_qa/test_models.py
git commit -m "feat(eval): golden-set models for knowledge-QA eval"
```

---

### Task 2: JSON loader + seed fixture

**Files:**
- Create: `eval/knowledge_qa/golden_set.py`
- Create: `eval/knowledge_qa/golden_set.json`
- Test: `tests/eval/knowledge_qa/test_golden_set.py`

- [ ] **Step 1: Create the seed fixture `eval/knowledge_qa/golden_set.json`**

Two cases — one answerable, one abstain — to lock the schema. Plan 05 grows this
to ≥30.

```json
{
  "version": 1,
  "cases": [
    {
      "id": "hust-quota-cntt-2026",
      "question": "Chỉ tiêu tuyển sinh ngành Khoa học Máy tính của HUST năm 2026 là bao nhiêu?",
      "school": "hust",
      "topic": "quota",
      "chunks": [
        {
          "chunk_text": "Năm 2026, ngành Khoa học Máy tính (mã IT1) của Đại học Bách khoa Hà Nội tuyển 300 chỉ tiêu theo phương thức xét điểm thi tốt nghiệp THPT.",
          "score": 0.83,
          "school": "hust",
          "topic": "quota",
          "source_url": "https://hust.edu.vn/tuyensinh-2026"
        },
        {
          "chunk_text": "Học phí chương trình chuẩn năm học 2026 dao động 24-30 triệu đồng/năm.",
          "score": 0.55,
          "school": "hust",
          "topic": "tuition",
          "source_url": "https://hust.edu.vn/hocphi-2026"
        }
      ],
      "expected_answer_points": ["300 chỉ tiêu"],
      "expected_source_ids": [1],
      "abstain": false
    },
    {
      "id": "hust-scholarship-abstain",
      "question": "Trường có học bổng toàn phần cho thủ khoa đầu vào không?",
      "school": "hust",
      "topic": "scholarship",
      "chunks": [
        {
          "chunk_text": "Năm 2026, ngành Khoa học Máy tính (mã IT1) của Đại học Bách khoa Hà Nội tuyển 300 chỉ tiêu theo phương thức xét điểm thi tốt nghiệp THPT.",
          "score": 0.42,
          "school": "hust",
          "topic": "quota",
          "source_url": "https://hust.edu.vn/tuyensinh-2026"
        }
      ],
      "expected_answer_points": [],
      "expected_source_ids": [],
      "abstain": true
    }
  ]
}
```

- [ ] **Step 2: Write the failing test `tests/eval/knowledge_qa/test_golden_set.py`**

```python
from pathlib import Path

from eval.knowledge_qa.golden_set import DEFAULT_GOLDEN_PATH, load_golden_set
from eval.knowledge_qa.models import GoldenCase


def test_loads_seed_fixture():
    cases = load_golden_set()

    assert len(cases) >= 2
    assert all(isinstance(c, GoldenCase) for c in cases)

    answerable = next(c for c in cases if c.id == "hust-quota-cntt-2026")
    assert answerable.abstain is False
    assert answerable.expected_source_ids == [1]
    assert answerable.chunks[0].to_scored_chunk().score == 0.83

    abstain = next(c for c in cases if c.id == "hust-scholarship-abstain")
    assert abstain.abstain is True
    assert abstain.expected_answer_points == []


def test_default_path_points_at_packaged_fixture():
    assert DEFAULT_GOLDEN_PATH == Path(__file__).resolve().parents[3] / "eval" / "knowledge_qa" / "golden_set.json"
```

> The `parents[3]` walk: `test_golden_set.py` → `knowledge_qa` → `eval` →
> `tests` → repo root. Adjust if the repo layout differs; the intent is "repo
> root / eval / knowledge_qa / golden_set.json".

- [ ] **Step 3: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/eval/knowledge_qa/test_golden_set.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'eval.knowledge_qa.golden_set'`.

- [ ] **Step 4: Implement `eval/knowledge_qa/golden_set.py`**

```python
import json
from pathlib import Path
from typing import Optional

from eval.knowledge_qa.models import GoldenCase

DEFAULT_GOLDEN_PATH = Path(__file__).resolve().parent / "golden_set.json"


def load_golden_set(path: Optional[Path] = None) -> list[GoldenCase]:
    """Load and validate the golden set. Raises on malformed JSON or schema
    violations so a broken fixture fails loudly rather than silently skewing the
    eval."""
    path = path or DEFAULT_GOLDEN_PATH
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [GoldenCase.model_validate(case) for case in data["cases"]]
```

- [ ] **Step 5: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/eval/knowledge_qa/test_golden_set.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add eval/knowledge_qa/golden_set.py eval/knowledge_qa/golden_set.json \
  tests/eval/knowledge_qa/test_golden_set.py
git commit -m "feat(eval): golden-set JSON loader + seed fixture"
```

---

## Done-check for Plan 02

Run: `.venv/bin/python -m pytest tests/eval -q`
Expected: PASS. The `eval/` package is importable and the seed fixture validates.
