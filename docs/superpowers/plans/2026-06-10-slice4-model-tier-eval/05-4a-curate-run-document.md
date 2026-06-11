# Plan 05 — 4a: Curate, run, document, gated swap

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Snapshot real retrieval into a ≥30-case golden set (LLM-drafted,
human-verified), run the flash-vs-flash-lite eval, commit the documented report,
and — **only if** the report passes — swap `knowledge_qa_agent` to flash-lite.

**Architecture:** A `retrieve` hook exposes production retrieval so curation
freezes the same chunks production would see. A `curate.py` driver runs retrieval
for seed questions and LLM-drafts expected grounding for human review. The
eval run and the model swap are gated, documented steps — the swap is a separate
commit made only on a PASS verdict.

**Tech Stack:** Python, Pydantic v2, pytest. Requires Docker DB + a valid Gemini
key for the curation + run steps (live calls). Depends on Plans 02–04.

> **This plan mixes automated code (Tasks 1–2) with manual, judgment steps
> (Tasks 3–5).** The manual steps cannot be auto-verified; follow the checklists
> and record outcomes.

---

### Task 1: `retrieve` hook on `KnowledgeQAService`

Curation must freeze the *same* chunks production retrieval would surface.

**Files:**
- Modify: `services/knowledge/qa_service.py`
- Test: `tests/services/knowledge/test_qa_retrieve.py`

- [ ] **Step 1: Write the failing test**

```python
from services.knowledge.models import ScoredChunk
from services.knowledge.qa_service import KnowledgeQAService


class _FakeEmbedder:
    def embed(self, texts, task_type=None):
        return [[0.1, 0.2, 0.3] for _ in texts]


class _FakeRepo:
    def __init__(self):
        self.calls = []

    def vector_search(self, embedding, school=None, topic=None, limit=None):
        self.calls.append((school, topic))
        return [ScoredChunk(chunk_text=f"{school}:{topic}", score=0.7, school=school or "x")]


def test_retrieve_embeds_once_and_returns_chunks():
    repo = _FakeRepo()
    svc = KnowledgeQAService(chunk_repository=repo, embedder=_FakeEmbedder(), gateway=object())

    chunks = svc.retrieve("Chỉ tiêu?", school="hust", topic="quota")

    assert chunks and isinstance(chunks[0], ScoredChunk)
    assert ("hust", "quota") in repo.calls
```

> A school-scoped query also triggers a national-scope search via
> `_augment_with_national`; the fake repo answers both calls, so `repo.calls` may
> contain a `(NATIONAL_SCHOOL, "quota")` entry too. The assertion only requires
> the school-scoped call is present.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/services/knowledge/test_qa_retrieve.py -q`
Expected: FAIL — `AttributeError: ... has no attribute 'retrieve'`.

- [ ] **Step 3: Add `retrieve` to `services/knowledge/qa_service.py`**

Insert on `KnowledgeQAService` (next to `generate_from_chunks`):

```python
    def retrieve(self, question: str, school, topic):
        """Production-equivalent retrieval (embed → vector_search → national
        augment), exposed so the eval curation can freeze the same chunks
        production would surface. Mirrors answer()'s retrieval branch."""
        embedding = self.embed_query(question)
        chunks = self._chunk_repository.vector_search(
            embedding, school=school, topic=topic, limit=self._top_k
        )
        return self._augment_with_national(embedding, school, topic, chunks)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/services/knowledge/test_qa_retrieve.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/knowledge/qa_service.py tests/services/knowledge/test_qa_retrieve.py
git commit -m "feat(knowledge): retrieve hook (production-equivalent, for eval curation)"
```

---

### Task 2: Curation driver

A one-off driver (like `scripts/`) — **not** part of the test suite. It reads
seed questions, freezes real retrieval, and LLM-drafts expected grounding into a
candidate file for human review.

**Files:**
- Create: `eval/knowledge_qa/curation_seeds.json`
- Create: `eval/knowledge_qa/curate.py`
- Test: `tests/eval/knowledge_qa/test_curate_smoke.py`

- [ ] **Step 1: Create a seed list `eval/knowledge_qa/curation_seeds.json`**

Aim for ≥30 entries spanning schools/topics already in the corpus (HUST, VNU-UET,
NEU, …) and topics (quota, tuition, admission_method, scholarship, cutoff).
Include ~5 deliberate `abstain` seeds whose answer is NOT in the corpus. Start
with these and expand:

```json
{
  "seeds": [
    {"question": "Chỉ tiêu ngành Khoa học Máy tính của HUST năm 2026 là bao nhiêu?", "school": "hust", "topic": "quota", "abstain": false},
    {"question": "Học phí ngành CNTT của VNU-UET năm 2026 khoảng bao nhiêu?", "school": "vnu_uet", "topic": "tuition", "abstain": false},
    {"question": "HUST có những phương thức xét tuyển nào năm 2026?", "school": "hust", "topic": "admission_method", "abstain": false},
    {"question": "Trường có ký túc xá miễn phí cho sinh viên năm nhất không?", "school": "hust", "topic": "scholarship", "abstain": true}
  ]
}
```

- [ ] **Step 2: Implement `eval/knowledge_qa/curate.py`**

```python
"""One-off curation driver (NOT in the test suite). Requires the Docker DB and a
Gemini key. Freezes real retrieval per seed and LLM-drafts expected grounding,
emitting a candidate golden set for HUMAN review before it becomes golden_set.json.
Run: python -m eval.knowledge_qa.curate
"""
import json
from pathlib import Path

from eval.knowledge_qa.gateways import build_judge_gateway
from services.inference.models import InferenceError, InferenceRequest
from services.knowledge.qa_service import KnowledgeQAService

SEEDS_PATH = Path(__file__).resolve().parent / "curation_seeds.json"
CANDIDATE_PATH = Path(__file__).resolve().parent / "golden_set.candidate.json"

DRAFT_SYSTEM_PROMPT = """
Bạn giúp tạo dữ liệu đánh giá. Cho một câu hỏi và các đoạn tham khảo đánh số,
hãy nêu các ý đúng mà một câu trả lời tốt phải có, và số thứ tự các đoạn chứa
thông tin đó. Trả về JSON: {"expected_answer_points": [...], "expected_source_ids": [...]}.
Nếu các đoạn KHÔNG đủ thông tin để trả lời, trả về cả hai mảng rỗng.
""".strip()


def _draft_grounding(question, chunks, gateway):
    numbered = "\n".join(f"[{i}] {c.chunk_text}" for i, c in enumerate(chunks, start=1))
    try:
        result = gateway.run(
            InferenceRequest(
                agent_name="qa_eval_judge", task_type="qa_eval_curate",
                system_prompt=DRAFT_SYSTEM_PROMPT,
                user_prompt=f"Câu hỏi: {question}\n\nCác đoạn:\n{numbered}",
                output_mode="json", temperature=0.0,
            )
        )
    except InferenceError:
        return {"expected_answer_points": [], "expected_source_ids": []}
    data = result.parsed_data or {}
    return {
        "expected_answer_points": data.get("expected_answer_points", []) or [],
        "expected_source_ids": data.get("expected_source_ids", []) or [],
    }


def _freeze_chunk(chunk):
    return {
        "chunk_text": chunk.chunk_text,
        "score": round(float(chunk.score), 4),
        "school": chunk.school,
        "topic": chunk.topic,
        "source_url": chunk.source_url,
    }


def main():
    seeds = json.loads(SEEDS_PATH.read_text(encoding="utf-8"))["seeds"]
    service = KnowledgeQAService()          # real DB + embedder
    gateway = build_judge_gateway()
    cases = []
    for n, seed in enumerate(seeds, start=1):
        chunks = service.retrieve(seed["question"], seed.get("school"), seed.get("topic"))
        frozen = [_freeze_chunk(c) for c in chunks]
        if seed.get("abstain"):
            grounding = {"expected_answer_points": [], "expected_source_ids": []}
        else:
            grounding = _draft_grounding(seed["question"], chunks, gateway)
        cases.append({
            "id": f"seed-{n:02d}",
            "question": seed["question"],
            "school": seed.get("school"),
            "topic": seed.get("topic"),
            "chunks": frozen,
            "abstain": bool(seed.get("abstain")),
            **grounding,
        })
    CANDIDATE_PATH.write_text(
        json.dumps({"version": 1, "cases": cases}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {len(cases)} candidate cases to {CANDIDATE_PATH}")
    print("REVIEW BY HAND, then move to golden_set.json.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Write + run a smoke test `tests/eval/knowledge_qa/test_curate_smoke.py`**

```python
def test_curate_module_imports():
    import eval.knowledge_qa.curate as curate

    assert callable(curate.main)
    assert curate.SEEDS_PATH.name == "curation_seeds.json"
```

Run: `.venv/bin/python -m pytest tests/eval/knowledge_qa/test_curate_smoke.py -q`
Expected: PASS.

- [ ] **Step 4: Commit the tooling (not yet the curated data)**

```bash
git add eval/knowledge_qa/curate.py eval/knowledge_qa/curation_seeds.json \
  tests/eval/knowledge_qa/test_curate_smoke.py
git commit -m "feat(eval): curation driver + seed questions"
```

---

### Task 3: Curate the golden set (manual)

- [ ] **Step 1: Bring up the DB and run curation**

```bash
docker compose up -d --wait db
.venv/bin/python -m eval.knowledge_qa.curate
```

Produces `eval/knowledge_qa/golden_set.candidate.json`.

- [ ] **Step 2: Human review — verify EVERY case**

For each candidate case: confirm the question is realistic; the frozen chunks are
the real retrieval; `expected_answer_points` are actually supported by the chunks
(fix LLM drafting errors); `expected_source_ids` point at the right chunks;
`abstain` cases truly lack the answer in their chunks. Ensure ≥30 cases including
~5 abstain cases. Edit IDs to be descriptive (e.g. `hust-quota-cntt-2026`).

- [ ] **Step 3: Promote to the golden set and validate**

Move the reviewed file to `eval/knowledge_qa/golden_set.json` (replacing the seed
fixture), then validate it loads:

```bash
.venv/bin/python -c "from eval.knowledge_qa.golden_set import load_golden_set; print(len(load_golden_set()))"
```

Expected: prints a count ≥30. Then run the loader test:

Run: `.venv/bin/python -m pytest tests/eval/knowledge_qa/test_golden_set.py -q`
Expected: PASS (update the two `id`-specific assertions in that test if you renamed
the seed cases, or keep two of the originals).

- [ ] **Step 4: Commit the curated golden set**

```bash
git add eval/knowledge_qa/golden_set.json
git rm --cached eval/knowledge_qa/golden_set.candidate.json 2>/dev/null || true
git commit -m "data(eval): curated knowledge-QA golden set (>=30 cases, human-verified)"
```

> Add `eval/knowledge_qa/golden_set.candidate.json` to `.gitignore` — it is a
> regenerated scratch artifact.

---

### Task 4: Run the eval and document (manual)

- [ ] **Step 1: Run the eval**

```bash
.venv/bin/python -m eval.knowledge_qa.run
```

Writes `docs/superpowers/evals/2026-06-10-knowledge-qa-flash-vs-flash-lite.md`
and prints the table + verdict.

- [ ] **Step 2: Sanity-check the report**

Confirm both models ran over all cases, metrics are populated (not all-zero —
all-zero usually means an API/key failure), and the verdict line reads PASS or
FAIL with a reason.

- [ ] **Step 3: Commit the documented report**

```bash
git add docs/superpowers/evals/2026-06-10-knowledge-qa-flash-vs-flash-lite.md
git commit -m "docs(eval): knowledge-QA flash-vs-flash-lite results"
```

This satisfies the 4a acceptance ("documented eval results committed") **whether
the verdict is PASS or FAIL** — a negative result is still a documented result.

---

### Task 5: Gated model swap (ONLY if verdict is PASS)

If the report verdict is **FAIL**, stop here: `knowledge_qa_agent` stays on
`flash`. Note the decision in the report and do not edit `factory.py`.

If the verdict is **PASS**, do the swap as its own commit:

**Files:**
- Modify: `services/inference/factory.py:31-39`
- Test: `tests/services/inference/test_factory_knowledge_qa_model.py`

- [ ] **Step 1: Write the failing test**

```python
from services.inference.factory import build_default_gateway


def test_knowledge_qa_primary_is_flash_lite_with_flash_fallback():
    gw = build_default_gateway()
    policy = gw.registry.resolve("knowledge_qa_agent")

    assert policy.primary_model == "gemini-2.5-flash-lite"
    assert policy.allow_fallback is True
    assert policy.fallback_model == "gemini-2.5-flash"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/services/inference/test_factory_knowledge_qa_model.py -q`
Expected: FAIL — primary is still `gemini-2.5-flash`.

- [ ] **Step 3: Swap the primary in `services/inference/factory.py`**

In the `knowledge_qa_agent` override, change the model tiers (keep flash as the
fallback so a flash-lite hiccup still degrades to the stronger model):

```python
            "knowledge_qa_agent": {
                "primary_model": "gemini-2.5-flash-lite",
                "output_mode": "json",
                "max_retries": 1,
                "allow_fallback": True,
                "fallback_model": "gemini-2.5-flash",
                "max_tokens": 800,
                "thinking_budget": 0,
            },
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/services/inference/test_factory_knowledge_qa_model.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/inference/factory.py tests/services/inference/test_factory_knowledge_qa_model.py
git commit -m "perf(inference): downgrade knowledge_qa_agent primary to flash-lite (eval-backed)"
```

---

## Done-check for Plan 05

Run: `.venv/bin/python -m pytest -q`
Expected: PASS against `admission_test` (Docker DB up).

Acceptance (spec 4a): documented eval results committed under
`docs/superpowers/evals/`; the `factory.py` primary-model change is merged **only**
on a PASS verdict, otherwise the negative result is recorded and no model change
ships.
