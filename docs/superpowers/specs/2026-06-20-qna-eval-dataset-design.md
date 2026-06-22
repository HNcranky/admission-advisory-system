# QnA Evaluation Dataset — Auto-Generation Design

**Date:** 2026-06-20
**Status:** Approved (brainstorming)
**Topic:** Generate a corpus-grounded QnA evaluation dataset for the knowledge-QA RAG.

## Problem

The only existing Langfuse QnA dataset (`QnA-admission`, 100 items, HSA/TSA exam
logistics) is **domain-mismatched** to the ingested corpus (HUST / NEU / VNU-UET /
MOET admission policy, quota, method, tuition, program docs). Running quality
metrics on it measures corpus coverage gap, not answer quality.

We need an eval dataset whose questions are **provably answerable from the current
corpus**, so correctness / faithfulness / answer-relevance scores reflect the
model and retrieval — not a content gap.

## Goal

A reusable evaluation dataset of ~50 question / reference-answer pairs, each
grounded in a real ingested chunk, stratified across schools and topics. Stored
versioned in-repo and pushed to a Langfuse dataset for `run_experiment` scoring.

Non-goals: abstention testing, end-to-end advisory eval, real student-log
curation. Those are separate datasets/specs.

## Approach (chosen)

**Auto-generate from ingested chunks.** Sample real chunks → one LLM call per
chunk writes a natural student question + a reference answer using *only* that
chunk. Grounding-by-construction makes the correctness judge fair and gives
faithfulness a real gold reference. Output to git JSON **and** Langfuse (repo copy
keeps it reproducible/reviewable; Langfuse copy drives experiments).

## Data Model

One dataset item:

```json
{
  "input": "<student-phrased question, Vietnamese>",
  "expected_output": "<reference answer grounded ONLY in the source chunk>",
  "metadata": {
    "school": "HUST",
    "topic": "admission_policy",
    "source_chunk_id": 1234,
    "source_url": "https://...",
    "program": null
  }
}
```

`source_chunk_id` enables a future **retrieval-recall** metric (did live retrieval
surface the gold chunk?) at zero extra cost. `school` / `topic` enable score
slicing in Langfuse.

## Sampling

Per-school target ~12 (≈50 total), stratified across the topics each school
actually has (from the 2026-06-20 corpus census):

| school  | chunks | topics present (chunks)                                   |
|---------|--------|-----------------------------------------------------------|
| HUST    | 462    | program_overview 301, admission_policy 78, tuition 13, (null) 70 |
| NEU     | 1252   | program_overview 1160, (null) 92                          |
| VNU-UET | 56     | program_overview 28, admission_policy 25, tuition 3       |
| MOET    | 152    | admission_policy 19, (null) 133                           |

Rules:
- Stratify within school: spread the school's ~12 across its present topics
  (proportional, min 1 per non-empty topic where possible).
- Filter `length(chunk_text) > 400` — short chunks rarely support a self-contained
  Q/A.
- **Deterministic** selection: `ORDER BY id`, evenly spaced pick across each
  (school, topic) group. No randomness (matches repo discipline; reproducible runs).

## Generator Pipeline

`scripts/gen_eval_dataset.py` (one-off driver, NOT in the test suite):

1. **Sample** chunks per the rules above (single SQL read via
   `services.db.cursor` + `services.knowledge.db.get_knowledge_db_connection`).
2. **Generate** — per chunk, one `gateway.run(InferenceRequest(...))` call
   (`output_mode="json"`, `temperature=0.0`). Gateway built like
   `eval/knowledge_qa/gateways.py::build_model_gateway` with a dedicated
   `qna_dataset_gen` agent override (flash, no fallback, json). Prompt instructs:
   write ONE natural Vietnamese student question fully answerable from the passage
   + a concise answer using ONLY the passage → JSON `{"question","answer"}`.
3. **Validate** — drop empty / malformed JSON (`failure_type` or missing keys);
   dedup by normalized question; drop leakage (question ⊆ answer or vice-versa);
   `log` every drop with reason (no silent truncation).
4. **Write** `eval/knowledge_qa/qna_corpus_eval.json` (git-tracked).
5. **Push** (separate `--push` flag) — create Langfuse dataset
   `qna-corpus-eval-v1` if absent, upload items via the SDK. Idempotent: items
   keyed so a re-push doesn't duplicate.

## Error Handling / Guards

- Throttle: inter-call delay, env-tunable (`GEN_CALL_DELAY_SECONDS`, default 2.0),
  mirroring `run.py` — the free-tier Gemini key pool trips per-key cooldowns on
  bursts.
- Degrade: on `InferenceError` or structure failure for a chunk, `logger.warning`
  and skip that chunk (don't abort the run). Final count may be < target; the
  console summary reports requested vs produced per (school, topic).
- Re-runnable: writing the JSON is idempotent; `--push` upserts.

## Outputs

- `eval/knowledge_qa/qna_corpus_eval.json` — the dataset (git, source of truth).
- `eval/knowledge_qa/qna_corpus_eval.csv` — flat CSV for the **Langfuse UI**
  dataset importer (columns: `input`, `expected_output`, `school`, `topic`,
  `source_chunk_id`, `source_url`, `program`; utf-8-sig). Always written.
- Langfuse dataset `qna-corpus-eval-v1` (only on `--push`, SDK path — alternative
  to the UI/CSV path).
- Console: per-(school, topic) produced/requested table + total.

`--from-json <path>` re-emits the CSV (and `--push`) from an existing JSON with no
DB/LLM cost — used to (re)generate the CSV after a generation run.

## Testing

This is a generation driver over live DB + LLM, like other `scripts/` probes —
not unit-tested. Validation is the in-pipeline guards + a manual review pass of
the JSON before `--push`. (Auto-gen-then-review path.)

## Follow-ups (out of scope here)

- Wire the full `run_experiment` quality eval (correctness / faithfulness /
  answer_relevance + retrieval-recall) over this dataset — separate step, reuses
  `scripts/coverage_probe.py` shape.
- Optional human edit pass on `qna_corpus_eval.json` before pushing.
