# Plan 03 — 4a: Hybrid grader

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Grade one model's answer to one golden case along four axes:
abstention-correctness and citation-F1 (deterministic) plus faithfulness and
factual correctness (LLM judge). All graders are pure functions over a
`KnowledgeQAResult`; the judge takes an injected gateway so unit tests never hit
a live model.

**Architecture:** `grader.py` exposes deterministic helpers
(`abstention_correct`, `citation_f1`) and an `judge_answer(...)` that calls a
fixed-`flash` judge via an injected gateway, then `grade_case(...)` combines them
into a `CaseGrade`. Abstain cases skip the judge (no expected answer).

**Tech Stack:** Python, Pydantic v2, pytest. Depends on Plan 02 models.

---

### Task 1: Deterministic graders + `CaseGrade`

**Files:**
- Create: `eval/knowledge_qa/grader.py` (deterministic portion first)
- Test: `tests/eval/knowledge_qa/test_grader.py`

- [ ] **Step 1: Write the failing test (deterministic part)**

`tests/eval/knowledge_qa/test_grader.py`:

```python
from eval.knowledge_qa.grader import (
    CaseGrade, abstention_correct, citation_f1, grade_case,
)
from eval.knowledge_qa.models import GoldenCase, GoldenChunk
from services.knowledge.models import Citation, KnowledgeQAResult


def _chunks():
    return [
        GoldenChunk(chunk_text="A: chỉ tiêu 300.", score=0.8, school="hust"),
        GoldenChunk(chunk_text="B: học phí 25 triệu.", score=0.6, school="hust"),
    ]


def _answer_citing(idx_texts):
    return KnowledgeQAResult(
        has_data=True,
        answer="Chỉ tiêu là 300.",
        citations=[Citation(source_url="", chunk_text=t) for t in idx_texts],
        confidence=0.8,
    )


def test_abstention_correct():
    answered = KnowledgeQAResult(has_data=True, answer="có 300", confidence=0.8)
    empty = KnowledgeQAResult(has_data=False, answer="", confidence=0.3)

    assert abstention_correct(answered, abstain=False) is True
    assert abstention_correct(answered, abstain=True) is False
    assert abstention_correct(empty, abstain=True) is True
    assert abstention_correct(empty, abstain=False) is False


def test_citation_f1_perfect_and_miss():
    chunks = [c.to_scored_chunk() for c in _chunks()]

    perfect = _answer_citing(["A: chỉ tiêu 300."])
    assert citation_f1(perfect, expected_source_ids=[1], chunks=chunks) == 1.0

    wrong = _answer_citing(["B: học phí 25 triệu."])
    assert citation_f1(wrong, expected_source_ids=[1], chunks=chunks) == 0.0

    none_expected_none_cited = KnowledgeQAResult(has_data=False, answer="", confidence=0.2)
    assert citation_f1(none_expected_none_cited, expected_source_ids=[], chunks=chunks) == 1.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/eval/knowledge_qa/test_grader.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'eval.knowledge_qa.grader'`.

- [ ] **Step 3: Implement the deterministic part of `eval/knowledge_qa/grader.py`**

```python
import json

from pydantic import BaseModel

from eval.knowledge_qa.models import GoldenCase
from services.inference.models import InferenceError, InferenceRequest
from services.knowledge.models import KnowledgeQAResult


class CaseGrade(BaseModel):
    case_id: str
    model: str
    answered: bool
    abstention_correct: bool
    # None on abstain cases (no expected answer to judge) or judge failure.
    faithful: bool | None = None
    correct: bool | None = None
    citation_f1: float | None = None


def _answered(result: KnowledgeQAResult) -> bool:
    return bool(result.has_data and (result.answer or "").strip())


def abstention_correct(result: KnowledgeQAResult, abstain: bool) -> bool:
    """Abstain cases are correct iff the model produced no answer; answerable
    cases are correct iff it produced one."""
    return (not _answered(result)) if abstain else _answered(result)


def _cited_indices(result: KnowledgeQAResult, chunks) -> set:
    """Map each citation back to its 1-based chunk index by exact text match."""
    idx = set()
    for cit in result.citations:
        for i, ch in enumerate(chunks, start=1):
            if ch.chunk_text == cit.chunk_text:
                idx.add(i)
    return idx


def citation_f1(result: KnowledgeQAResult, expected_source_ids, chunks) -> float:
    expected = set(expected_source_ids)
    cited = _cited_indices(result, chunks)
    if not expected and not cited:
        return 1.0
    if not expected or not cited:
        return 0.0
    tp = len(expected & cited)
    if tp == 0:
        return 0.0
    precision = tp / len(cited)
    recall = tp / len(expected)
    return 2 * precision * recall / (precision + recall)
```

- [ ] **Step 4: Run to verify the deterministic tests pass**

Run: `.venv/bin/python -m pytest tests/eval/knowledge_qa/test_grader.py -q`
Expected: PASS (the `grade_case` import resolves; its tests are added in Task 2).

- [ ] **Step 5: Commit**

```bash
git add eval/knowledge_qa/grader.py tests/eval/knowledge_qa/test_grader.py
git commit -m "feat(eval): deterministic abstention + citation-F1 graders"
```

---

### Task 2: LLM judge + `grade_case` combiner

**Files:**
- Modify: `eval/knowledge_qa/grader.py` (append the judge + combiner)
- Test: `tests/eval/knowledge_qa/test_grader.py` (append)

- [ ] **Step 1: Append the failing tests**

Add to `tests/eval/knowledge_qa/test_grader.py`:

```python
from services.inference.models import InferenceResult


class _FakeJudgeGateway:
    """Returns a canned judge verdict; records the request for assertions."""

    def __init__(self, faithful, correct):
        self._verdict = {"faithful": faithful, "correct": correct}
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        return InferenceResult(
            agent_name="qa_eval_judge", model="gemini-2.5-flash", provider="fake",
            content="{}", parsed_data=self._verdict,
        )


def _golden(abstain=False, expected_ids=(1,)):
    return GoldenCase(
        id="c1", question="Chỉ tiêu?", school="hust", topic="quota",
        chunks=_chunks(), expected_answer_points=["300"],
        expected_source_ids=list(expected_ids), abstain=abstain,
    )


def test_grade_case_answered_uses_judge():
    gateway = _FakeJudgeGateway(faithful=True, correct=True)
    result = _answer_citing(["A: chỉ tiêu 300."])

    grade = grade_case(_golden(), result, model="gemini-2.5-flash-lite", gateway=gateway)

    assert grade.model == "gemini-2.5-flash-lite"
    assert grade.answered is True
    assert grade.abstention_correct is True
    assert grade.faithful is True and grade.correct is True
    assert grade.citation_f1 == 1.0
    assert len(gateway.requests) == 1


def test_grade_case_abstain_skips_judge():
    gateway = _FakeJudgeGateway(faithful=True, correct=True)
    empty = KnowledgeQAResult(has_data=False, answer="", confidence=0.2)

    grade = grade_case(_golden(abstain=True, expected_ids=()), empty,
                       model="gemini-2.5-flash", gateway=gateway)

    assert grade.abstention_correct is True
    assert grade.faithful is None and grade.correct is None
    assert gateway.requests == []  # judge never called on abstain cases


def test_grade_case_non_abstain_declined_is_incorrect_no_judge():
    gateway = _FakeJudgeGateway(faithful=True, correct=True)
    empty = KnowledgeQAResult(has_data=False, answer="", confidence=0.2)

    grade = grade_case(_golden(), empty, model="gemini-2.5-flash", gateway=gateway)

    assert grade.answered is False
    assert grade.abstention_correct is False
    assert grade.correct is False
    assert grade.citation_f1 == 0.0
    assert gateway.requests == []  # no answer to judge
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `.venv/bin/python -m pytest tests/eval/knowledge_qa/test_grader.py -q`
Expected: FAIL — `grade_case` / `judge_answer` not defined.

- [ ] **Step 3: Append the judge + combiner to `eval/knowledge_qa/grader.py`**

```python
JUDGE_SYSTEM_PROMPT = """
Bạn là giám khảo đánh giá câu trả lời của một trợ lý tuyển sinh.
Bạn nhận: câu hỏi, các đoạn văn bản tham khảo, các ý đúng kỳ vọng, và câu trả lời.
Đánh giá hai tiêu chí, chỉ dựa trên các đoạn tham khảo:
- faithful: true nếu câu trả lời CHỈ dùng thông tin có trong các đoạn tham khảo,
  không bịa thêm; false nếu có thông tin ngoài các đoạn.
- correct: true nếu câu trả lời nêu đúng các ý đúng kỳ vọng; false nếu sai/thiếu.
Trả về JSON hợp lệ, không giải thích: {"faithful": <bool>, "correct": <bool>}
""".strip()


def judge_answer(question, scored_chunks, expected_points, answer, gateway) -> dict:
    payload = {
        "question": question,
        "chunks": [c.chunk_text for c in scored_chunks],
        "expected_points": expected_points,
        "answer": answer,
    }
    try:
        result = gateway.run(
            InferenceRequest(
                agent_name="qa_eval_judge",
                task_type="qa_eval_judge",
                system_prompt=JUDGE_SYSTEM_PROMPT,
                user_prompt=json.dumps(payload, ensure_ascii=False),
                output_mode="json",
                temperature=0.0,
            )
        )
    except InferenceError:
        return {"faithful": None, "correct": None}
    data = result.parsed_data or {}
    return {
        "faithful": bool(data["faithful"]) if "faithful" in data else None,
        "correct": bool(data["correct"]) if "correct" in data else None,
    }


def grade_case(case: GoldenCase, result: KnowledgeQAResult, model: str, gateway) -> CaseGrade:
    answered = _answered(result)
    scored = [c.to_scored_chunk() for c in case.chunks]
    grade = CaseGrade(
        case_id=case.id,
        model=model,
        answered=answered,
        abstention_correct=abstention_correct(result, case.abstain),
    )
    if case.abstain:
        # No expected answer -> faithfulness/correctness not applicable.
        return grade

    grade.citation_f1 = citation_f1(result, case.expected_source_ids, scored)
    if answered:
        verdict = judge_answer(
            case.question, scored, case.expected_answer_points, result.answer or "", gateway
        )
        grade.faithful = verdict["faithful"]
        grade.correct = verdict["correct"]
    else:
        # Should have answered but declined -> a correctness miss, nothing to judge.
        grade.correct = False
    return grade
```

- [ ] **Step 4: Run to verify all grader tests pass**

Run: `.venv/bin/python -m pytest tests/eval/knowledge_qa/test_grader.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add eval/knowledge_qa/grader.py tests/eval/knowledge_qa/test_grader.py
git commit -m "feat(eval): LLM-judge faithfulness/correctness + grade_case combiner"
```

---

## Done-check for Plan 03

Run: `.venv/bin/python -m pytest tests/eval -q`
Expected: PASS. Grader verified end-to-end with a mocked judge — no live LLM
calls in the test suite.
