# Knowledge-QA model-tier eval: flash vs flash-lite

Baseline: `gemini-2.5-flash` · Candidate: `gemini-2.5-flash-lite` · Cases: 32

| Metric | `gemini-2.5-flash` | `gemini-2.5-flash-lite` |
|---|---|---|
| Faithfulness | 0.958 | 0.957 |
| Correctness | 0.769 | 0.615 |
| Citation F1 | 0.656 | 0.604 |
| Abstention acc. | 0.938 | 0.906 |

**Verdict:** FAIL — keep flash. Faithfulness regressed below baseline.

## Decision

`knowledge_qa_agent` **stays on `gemini-2.5-flash`**; the gated swap to flash-lite
is **not** applied (`services/inference/factory.py` unchanged).

The verdict line reports the first failing check (faithfulness, −0.001 — marginal),
but the regression is broader and decisive on the metric that matters most:

- **Correctness 0.769 → 0.615** (−0.154, far outside the ±0.05 tolerance) — flash-lite
  answers the grounded questions correctly ~15 points less often.
- Abstention accuracy 0.938 → 0.906 (−0.032) and Citation F1 0.656 → 0.604 also regress.
- Faithfulness is effectively tied (0.958 vs 0.957).

flash-lite does not match flash on this task, so the stronger model is retained.

## Run notes

- Golden set: 32 human-verified cases (26 answerable + 6 abstain), generation-only
  over frozen production-equivalent retrieval; judge fixed to `gemini-2.5-flash`.
- Clean run: **0 generation failures, 0 quota errors**. The free-tier key pool caps
  flash at 20 requests/day/project, so the run is paced (`EVAL_CALL_DELAY_SECONDS`)
  and retries short-window exhaustions (`EVAL_RETRY_ATTEMPTS`/`EVAL_RETRY_WAIT_SECONDS`)
  so rate limiting never degrades a generation into a false "no answer". Earlier
  unthrottled runs failed ~half their calls and produced invalid (much lower) numbers.
