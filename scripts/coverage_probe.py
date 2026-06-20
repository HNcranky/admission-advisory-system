r"""Coverage probe: does the live RAG corpus even cover the QnA-admission dataset?

Runs the REAL knowledge-QA pipeline (embed -> pgvector retrieve -> confidence
gate -> generate) over every item of the Langfuse dataset `QnA-admission` and
records whether the system produced a grounded answer (`has_data`) vs abstained.

This is the gate BEFORE investing in LLM-judge quality metrics: the dataset is
HSA/TSA exam-logistics Q, the corpus is admission policy/quota/program docs. If
coverage is low, a low correctness score means "corpus gap", not "bad model" —
fix the corpus (or reframe as an abstention test) first.

Emits one `context_coverage` score per item to a Langfuse dataset run, so traces
+ scores are visible in the UI (Datasets -> QnA-admission -> Runs). Also prints a
per-category breakdown to the console.

Run:
    .\.venv\Scripts\python.exe -m scripts.coverage_probe

Needs (.env, auto-loaded): GEMINI key, DB up, LANGFUSE_PUBLIC_KEY / SECRET_KEY /
HOST. Not part of the test suite — one-off probe driver.
"""

from __future__ import annotations

import os
import threading
from collections import defaultdict

try:  # standalone script: load .env the app normally loads for us
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv optional; rely on ambient env if absent
    pass

from langfuse import Evaluation, get_client

from services.knowledge.qa_service import KnowledgeQAService

DATASET_NAME = os.getenv("PROBE_DATASET", "QnA-admission")
RUN_NAME = os.getenv("PROBE_RUN_NAME", "coverage-probe")
# Embedding + generation hit the same rate-limited Gemini key pool as the eval
# runner — keep concurrency modest so a burst doesn't trip per-key cooldowns
# (a rate-limited call degrades to has_data=False and would fake a coverage miss).
MAX_CONCURRENCY = int(os.getenv("PROBE_CONCURRENCY", "3"))

# Per-category tally for the console breakdown. Guarded: run_experiment fans the
# task across threads, so the dict updates need a lock to stay consistent.
_tally: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # category -> [hits, total]
_lock = threading.Lock()


def _category(item) -> str:
    md = item.metadata
    if isinstance(md, dict):  # tolerate either raw-string or wrapped metadata
        return md.get("category") or md.get("Category") or "?"
    return md or "?"


def task(*, item, **kwargs):
    # Dataset item.input is the bare question string; no school/topic in this
    # dataset, so pass None/None -> no metadata filter, search the whole corpus,
    # and bypass the QA cache (clean retrieval every run).
    res = qa.answer(question=item.input, school=None, topic=None)
    cat = _category(item)
    with _lock:
        _tally[cat][1] += 1
        if res.has_data:
            _tally[cat][0] += 1
    return {
        "answer": res.answer or "",
        "has_data": res.has_data,
        "confidence": round(res.confidence, 3),
        "category": cat,
    }


def context_coverage(*, output, **kwargs):
    # Boolean coverage signal. Comment carries confidence + category so you can
    # slice/sort in the Langfuse Scores view without re-running.
    return Evaluation(
        name="context_coverage",
        value=bool(output["has_data"]),
        comment=f"conf={output['confidence']} cat={output['category']}",
    )


def coverage_rate(*, item_results, **kwargs):
    n = len(item_results) or 1
    hits = sum(1 for r in item_results if (r.output or {}).get("has_data"))
    return Evaluation(name="coverage_rate", value=hits / n,
                      comment=f"{hits}/{len(item_results)} items grounded")


def main() -> None:
    global qa
    qa = KnowledgeQAService()  # real repo + embedder + default gateway

    lf = get_client()
    if not lf.auth_check():
        raise SystemExit(
            "Langfuse not authenticated. Set LANGFUSE_PUBLIC_KEY / "
            "LANGFUSE_SECRET_KEY / LANGFUSE_HOST (in .env)."
        )

    dataset = lf.get_dataset(DATASET_NAME)
    result = dataset.run_experiment(
        name=RUN_NAME,
        description="Live-retrieval coverage probe (has_data rate) — corpus/domain gate",
        task=task,
        evaluators=[context_coverage],
        run_evaluators=[coverage_rate],
        max_concurrency=MAX_CONCURRENCY,
    )
    print(result.format())

    # Console breakdown: overall + per category, the actionable read for the gate.
    print("\n=== coverage by category (hits / total) ===")
    th, tt = 0, 0
    for cat in sorted(_tally):
        h, t = _tally[cat]
        th += h
        tt += t
        print(f"  {cat:<8} {h:>3}/{t:<3}  {h / (t or 1):.0%}")
    print(f"  {'ALL':<8} {th:>3}/{tt:<3}  {th / (tt or 1):.0%}")

    lf.flush()


if __name__ == "__main__":
    main()
