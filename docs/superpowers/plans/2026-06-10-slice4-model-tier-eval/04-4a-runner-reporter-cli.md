# Plan 04 — 4a: Model-forced runner, reporter, CLI

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run each golden case's frozen chunks through generation for both models
(flash, flash-lite) with retrieval bypassed, aggregate the grades into a
per-model report with a pass/fail parity verdict, and wire it behind
`python -m eval.knowledge_qa.run`.

**Architecture:** `gateways.py` builds model-forced gateways (no fallback, so the
measured model is the model). A new `KnowledgeQAService.generate_from_chunks`
exposes the generation-only path. `runner.run_case` feeds frozen chunks into it.
`reporter` aggregates `CaseGrade`s and renders markdown + verdict. `run.py` is
the opt-in CLI; it issues live LLM calls and is **not** in the test suite.

**Tech Stack:** Python, Pydantic v2, pytest. Depends on Plans 02–03.

---

### Task 1: Model-forced gateways

**Files:**
- Create: `eval/knowledge_qa/gateways.py`
- Test: `tests/eval/knowledge_qa/test_gateways.py`

- [ ] **Step 1: Write the failing test**

```python
from eval.knowledge_qa.gateways import build_judge_gateway, build_model_gateway


def test_model_gateway_forces_qa_agent_onto_model():
    gw = build_model_gateway("gemini-2.5-flash-lite")
    policy = gw.registry.resolve("knowledge_qa_agent")

    assert policy.primary_model == "gemini-2.5-flash-lite"
    assert policy.allow_fallback is False  # measure the model alone
    assert policy.thinking_budget == 0


def test_judge_gateway_is_fixed_flash():
    gw = build_judge_gateway()
    policy = gw.registry.resolve("qa_eval_judge")

    assert policy.primary_model == "gemini-2.5-flash"
    assert policy.allow_fallback is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/eval/knowledge_qa/test_gateways.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `eval/knowledge_qa/gateways.py`**

```python
from services.inference.gateway import LLMGateway
from services.inference.registry import ModelRegistry
from services.inference.telemetry import InferenceTelemetry


def build_model_gateway(model: str) -> LLMGateway:
    """Gateway that forces `knowledge_qa_agent` onto `model` with NO fallback, so
    the eval measures the model in isolation."""
    registry = ModelRegistry(
        default_model=model,
        agent_overrides={
            "knowledge_qa_agent": {
                "primary_model": model,
                "output_mode": "json",
                "max_retries": 1,
                "allow_fallback": False,
                "max_tokens": 800,
                "thinking_budget": 0,
            },
        },
    )
    return LLMGateway(registry=registry, telemetry=InferenceTelemetry())


def build_judge_gateway() -> LLMGateway:
    """A fixed `flash` judge, so the judge never confounds the flash-vs-flash-lite
    comparison."""
    registry = ModelRegistry(
        default_model="gemini-2.5-flash",
        agent_overrides={
            "qa_eval_judge": {
                "primary_model": "gemini-2.5-flash",
                "output_mode": "json",
                "max_retries": 1,
                "allow_fallback": False,
                "max_tokens": 300,
                "thinking_budget": 0,
            },
        },
    )
    return LLMGateway(registry=registry, telemetry=InferenceTelemetry())
```

> Confirm `LLMGateway` exposes its `registry` attribute (it is constructed with
> `registry=...` in `services/inference/factory.py`). If the attribute is named
> differently, adjust the test to match the real accessor.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/eval/knowledge_qa/test_gateways.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add eval/knowledge_qa/gateways.py tests/eval/knowledge_qa/test_gateways.py
git commit -m "feat(eval): model-forced + judge gateways"
```

---

### Task 2: `generate_from_chunks` generation hook

**Files:**
- Modify: `services/knowledge/qa_service.py`
- Test: `tests/services/knowledge/test_qa_generate_from_chunks.py`

- [ ] **Step 1: Write the failing test**

```python
from services.inference.models import InferenceResult
from services.knowledge.models import ScoredChunk
from services.knowledge.qa_service import KnowledgeQAService


class _FakeGateway:
    def __init__(self, parsed):
        self._parsed = parsed

    def run(self, request):
        return InferenceResult(
            agent_name="knowledge_qa_agent", model="m", provider="fake",
            content="{}", parsed_data=self._parsed,
        )


def _chunk(text, score, url="https://x"):
    return ScoredChunk(chunk_text=text, score=score, school="hust", source_url=url)


def test_generate_from_chunks_returns_grounded_answer():
    gw = _FakeGateway({"answer": "Chỉ tiêu là 300.", "used_source_ids": [1]})
    svc = KnowledgeQAService(chunk_repository=object(), embedder=object(), gateway=gw)

    out = svc.generate_from_chunks("Chỉ tiêu?", [_chunk("A 300", 0.8), _chunk("B 25tr", 0.6)])

    assert out.has_data is True
    assert out.answer == "Chỉ tiêu là 300."
    assert out.confidence == 0.8
    assert out.citations[0].chunk_text == "A 300"


def test_generate_from_chunks_empty_chunks_is_no_data():
    gw = _FakeGateway({"answer": "x"})
    svc = KnowledgeQAService(chunk_repository=object(), embedder=object(), gateway=gw)

    out = svc.generate_from_chunks("Chỉ tiêu?", [])

    assert out.has_data is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/services/knowledge/test_qa_generate_from_chunks.py -q`
Expected: FAIL — `AttributeError: 'KnowledgeQAService' object has no attribute 'generate_from_chunks'`.

- [ ] **Step 3: Add `generate_from_chunks` to `services/knowledge/qa_service.py`**

Insert this method on `KnowledgeQAService` (e.g. right after `answer`):

```python
    def generate_from_chunks(
        self, question: str, chunks, conversation_context: str = ""
    ) -> KnowledgeQAResult:
        """Eval hook: run only the model-dependent generation step on a fixed set
        of chunks, bypassing retrieval. Mirrors the post-retrieval branch of
        answer(), so what it measures is exactly what production runs."""
        confidence = chunks[0].score if chunks else 0.0
        if not chunks:
            return KnowledgeQAResult(has_data=False, confidence=confidence)
        return self._generate(question, chunks, confidence, conversation_context)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/services/knowledge/test_qa_generate_from_chunks.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/knowledge/qa_service.py tests/services/knowledge/test_qa_generate_from_chunks.py
git commit -m "feat(knowledge): generate_from_chunks eval hook (generation only, no retrieval)"
```

---

### Task 3: Runner

**Files:**
- Create: `eval/knowledge_qa/runner.py`
- Test: `tests/eval/knowledge_qa/test_runner.py`

- [ ] **Step 1: Write the failing test**

```python
import eval.knowledge_qa.runner as runner
from eval.knowledge_qa.models import GoldenCase, GoldenChunk
from services.knowledge.models import KnowledgeQAResult


class _FakeService:
    def __init__(self):
        self.seen = None

    def generate_from_chunks(self, question, chunks, conversation_context=""):
        self.seen = (question, chunks)
        return KnowledgeQAResult(has_data=True, answer="ok", confidence=chunks[0].score)


def test_run_case_feeds_frozen_chunks_to_forced_model(monkeypatch):
    fake = _FakeService()
    captured = {}

    def fake_service_for(model):
        captured["model"] = model
        return fake

    monkeypatch.setattr(runner, "_service_for", fake_service_for)

    case = GoldenCase(
        id="c1", question="Chỉ tiêu?", school="hust", topic="quota",
        chunks=[GoldenChunk(chunk_text="A 300", score=0.8, school="hust")],
    )

    result = runner.run_case(case, "gemini-2.5-flash-lite")

    assert result.answer == "ok"
    assert captured["model"] == "gemini-2.5-flash-lite"
    assert fake.seen[0] == "Chỉ tiêu?"
    assert fake.seen[1][0].score == 0.8   # ScoredChunk reconstructed from frozen chunk
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/eval/knowledge_qa/test_runner.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `eval/knowledge_qa/runner.py`**

```python
from eval.knowledge_qa.gateways import build_model_gateway
from eval.knowledge_qa.models import GoldenCase
from services.knowledge.models import KnowledgeQAResult
from services.knowledge.qa_service import KnowledgeQAService


def _service_for(model: str) -> KnowledgeQAService:
    # Retrieval is bypassed (generate_from_chunks), so the repository/embedder are
    # never used — pass sentinels to avoid constructing real DB/embedding clients.
    return KnowledgeQAService(
        chunk_repository=object(),
        embedder=object(),
        gateway=build_model_gateway(model),
    )


def run_case(case: GoldenCase, model: str) -> KnowledgeQAResult:
    service = _service_for(model)
    chunks = [c.to_scored_chunk() for c in case.chunks]
    return service.generate_from_chunks(case.question, chunks)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/eval/knowledge_qa/test_runner.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add eval/knowledge_qa/runner.py tests/eval/knowledge_qa/test_runner.py
git commit -m "feat(eval): model-forced runner over frozen chunks"
```

---

### Task 4: Reporter (aggregate + verdict + render)

**Files:**
- Create: `eval/knowledge_qa/reporter.py`
- Test: `tests/eval/knowledge_qa/test_reporter.py`

- [ ] **Step 1: Write the failing test**

```python
from eval.knowledge_qa.grader import CaseGrade
from eval.knowledge_qa.reporter import ModelReport, aggregate, render_report, verdict


def _grades(model, faithful, correct, cit, abst):
    """Build a uniform set of grades for a model from rate-like inputs."""
    return [
        CaseGrade(case_id=f"{model}-{i}", model=model, answered=True,
                  abstention_correct=a, faithful=f, correct=c, citation_f1=ci)
        for i, (f, c, ci, a) in enumerate(zip(faithful, correct, cit, abst))
    ]


def test_aggregate_computes_rates():
    grades = _grades("flash", faithful=[True, True], correct=[True, False],
                     cit=[1.0, 0.0], abst=[True, True])

    rep = aggregate(grades, "flash")

    assert isinstance(rep, ModelReport)
    assert rep.n_cases == 2
    assert rep.faithfulness_rate == 1.0
    assert rep.correctness_rate == 0.5
    assert rep.citation_f1_mean == 0.5
    assert rep.abstention_accuracy == 1.0


def test_verdict_pass_when_candidate_matches_within_tolerance():
    base = ModelReport(model="flash", n_cases=10, faithfulness_rate=0.9,
                       correctness_rate=0.9, citation_f1_mean=0.8, abstention_accuracy=0.95)
    cand = ModelReport(model="flash-lite", n_cases=10, faithfulness_rate=0.9,
                       correctness_rate=0.87, citation_f1_mean=0.78, abstention_accuracy=0.95)

    passed, _ = verdict(base, cand, tol=0.05)
    assert passed is True


def test_verdict_fails_on_faithfulness_regression():
    base = ModelReport(model="flash", n_cases=10, faithfulness_rate=0.9,
                       correctness_rate=0.9, citation_f1_mean=0.8, abstention_accuracy=0.95)
    cand = ModelReport(model="flash-lite", n_cases=10, faithfulness_rate=0.8,
                       correctness_rate=0.9, citation_f1_mean=0.8, abstention_accuracy=0.95)

    passed, reason = verdict(base, cand, tol=0.05)
    assert passed is False
    assert "faithful" in reason.lower()


def test_render_report_contains_models_and_verdict():
    base = ModelReport(model="gemini-2.5-flash", n_cases=2, faithfulness_rate=1.0,
                       correctness_rate=1.0, citation_f1_mean=1.0, abstention_accuracy=1.0)
    cand = ModelReport(model="gemini-2.5-flash-lite", n_cases=2, faithfulness_rate=1.0,
                       correctness_rate=1.0, citation_f1_mean=1.0, abstention_accuracy=1.0)

    md = render_report({"gemini-2.5-flash": base, "gemini-2.5-flash-lite": cand},
                       baseline="gemini-2.5-flash")

    assert "gemini-2.5-flash-lite" in md
    assert "Verdict" in md
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/eval/knowledge_qa/test_reporter.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `eval/knowledge_qa/reporter.py`**

```python
from pydantic import BaseModel


class ModelReport(BaseModel):
    model: str
    n_cases: int
    faithfulness_rate: float
    correctness_rate: float
    citation_f1_mean: float
    abstention_accuracy: float


def _rate(values) -> float:
    vals = [v for v in values if v is not None]
    if not vals:
        return 0.0
    return sum(1.0 if v is True else (0.0 if v is False else v) for v in vals) / len(vals)


def aggregate(grades, model: str) -> ModelReport:
    return ModelReport(
        model=model,
        n_cases=len(grades),
        faithfulness_rate=_rate([g.faithful for g in grades]),
        correctness_rate=_rate([g.correct for g in grades]),
        citation_f1_mean=_rate([g.citation_f1 for g in grades]),
        abstention_accuracy=_rate([g.abstention_correct for g in grades]),
    )


def verdict(baseline: ModelReport, candidate: ModelReport, tol: float = 0.05):
    """Candidate (flash-lite) passes only if it does not regress faithfulness or
    abstention, and stays within `tol` on correctness and citation F1."""
    if candidate.faithfulness_rate < baseline.faithfulness_rate:
        return False, "Faithfulness regressed below baseline."
    if candidate.abstention_accuracy < baseline.abstention_accuracy:
        return False, "Abstention accuracy regressed below baseline."
    if candidate.correctness_rate < baseline.correctness_rate - tol:
        return False, "Correctness fell outside tolerance."
    if candidate.citation_f1_mean < baseline.citation_f1_mean - tol:
        return False, "Citation F1 fell outside tolerance."
    return True, "Candidate matches baseline within tolerance."


def render_report(reports: dict, baseline: str, tol: float = 0.05) -> str:
    base = reports[baseline]
    cand_name = next(m for m in reports if m != baseline)
    cand = reports[cand_name]
    passed, reason = verdict(base, cand, tol=tol)

    lines = [
        "# Knowledge-QA model-tier eval: flash vs flash-lite",
        "",
        f"Baseline: `{baseline}` · Candidate: `{cand_name}` · Cases: {base.n_cases}",
        "",
        "| Metric | " + " | ".join(f"`{m}`" for m in reports) + " |",
        "|---|" + "---|" * len(reports),
    ]
    metrics = [
        ("Faithfulness", "faithfulness_rate"),
        ("Correctness", "correctness_rate"),
        ("Citation F1", "citation_f1_mean"),
        ("Abstention acc.", "abstention_accuracy"),
    ]
    for label, attr in metrics:
        row = [f"{getattr(reports[m], attr):.3f}" for m in reports]
        lines.append(f"| {label} | " + " | ".join(row) + " |")
    lines += [
        "",
        f"**Verdict:** {'PASS — adopt flash-lite' if passed else 'FAIL — keep flash'}. {reason}",
        "",
    ]
    return "\n".join(lines)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/eval/knowledge_qa/test_reporter.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add eval/knowledge_qa/reporter.py tests/eval/knowledge_qa/test_reporter.py
git commit -m "feat(eval): per-model aggregation + parity verdict + markdown report"
```

---

### Task 5: CLI entry point

**Files:**
- Create: `eval/knowledge_qa/run.py`
- Test: `tests/eval/knowledge_qa/test_run_smoke.py`

The CLI issues live LLM calls, so it is **not** exercised end-to-end in CI. The
smoke test only asserts it imports and exposes `main`.

- [ ] **Step 1: Write the failing smoke test**

```python
def test_run_module_exposes_main():
    import eval.knowledge_qa.run as run

    assert callable(run.main)
    assert "gemini-2.5-flash" in run.MODELS
    assert "gemini-2.5-flash-lite" in run.MODELS
    assert run.BASELINE == "gemini-2.5-flash"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/eval/knowledge_qa/test_run_smoke.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `eval/knowledge_qa/run.py`**

```python
from pathlib import Path

from eval.knowledge_qa.gateways import build_judge_gateway
from eval.knowledge_qa.golden_set import load_golden_set
from eval.knowledge_qa.grader import grade_case
from eval.knowledge_qa.reporter import aggregate, render_report
from eval.knowledge_qa.runner import run_case

MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
BASELINE = "gemini-2.5-flash"
REPORT_PATH = Path("docs/superpowers/evals/2026-06-10-knowledge-qa-flash-vs-flash-lite.md")


def main() -> None:
    cases = load_golden_set()
    judge = build_judge_gateway()
    grades = {m: [] for m in MODELS}

    for case in cases:
        for model in MODELS:
            result = run_case(case, model)
            grades[model].append(grade_case(case, result, model, judge))

    reports = {m: aggregate(grades[m], m) for m in MODELS}
    md = render_report(reports, baseline=BASELINE)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(md, encoding="utf-8")
    print(md)
    print(f"\nReport written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/eval/knowledge_qa/test_run_smoke.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add eval/knowledge_qa/run.py tests/eval/knowledge_qa/test_run_smoke.py
git commit -m "feat(eval): python -m eval.knowledge_qa.run CLI"
```

---

## Done-check for Plan 04

Run: `.venv/bin/python -m pytest tests/eval tests/services/knowledge/test_qa_generate_from_chunks.py -q`
Expected: PASS. The full harness is wired and unit-tested with mocks; no live LLM
calls run in the suite. The actual flash-vs-flash-lite run happens in Plan 05.
