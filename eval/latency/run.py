"""Runtime-latency eval for the knowledge-QA pipeline.

    python -m eval.latency.run            # default sample
    EVAL_LATENCY_N=20 python -m eval.latency.run

Times the production answer path end-to-end (`KnowledgeQAService.answer`:
embed → retrieve → generate) over a sample of the labelled corpus and reports
p50/p95/mean wall-clock, plus generation-only latency measured on frozen chunks
so the model step can be separated from retrieval. Needs the database up and a
Gemini key; calls are paced for the free-tier key pool.

Latency depends on network and the Gemini endpoint, so the absolute numbers are
environment-specific; the report records the run date and machine via the caller.
"""

import json
import os
import time
from pathlib import Path

CORPUS_PATH = Path("eval/knowledge_qa/qna_corpus_eval.json")
REPORT_PATH = Path("docs/superpowers/evals/latency-knowledge-qa.md")
SAMPLE_N = int(os.getenv("EVAL_LATENCY_N", "15"))
CALL_DELAY_SECONDS = float(os.getenv("EVAL_CALL_DELAY_SECONDS", "2.0"))


def _percentile(values, p):
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    frac = k - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * frac


def _summ(values):
    return {
        "n": len(values),
        "p50": _percentile(values, 50),
        "p95": _percentile(values, 95),
        "mean": sum(values) / len(values) if values else 0.0,
    }


def main() -> None:
    from services.knowledge.qa_service import KnowledgeQAService

    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))[:SAMPLE_N]
    service = KnowledgeQAService(cache_enabled=False)

    e2e = []
    gen = []
    for case in corpus:
        meta = case["metadata"]
        q = case["input"]

        start = time.perf_counter()
        service.answer(q, school=meta.get("school"), topic=meta.get("topic"))
        e2e.append((time.perf_counter() - start) * 1000.0)
        if CALL_DELAY_SECONDS:
            time.sleep(CALL_DELAY_SECONDS)

        # Generation-only on the chunks this question actually retrieves.
        chunks = service.retrieve(q, school=meta.get("school"), topic=meta.get("topic"))
        start = time.perf_counter()
        service.generate_from_chunks(q, chunks)
        gen.append((time.perf_counter() - start) * 1000.0)
        if CALL_DELAY_SECONDS:
            time.sleep(CALL_DELAY_SECONDS)

    se2e, sgen = _summ(e2e), _summ(gen)

    lines = ["# Knowledge-QA runtime-latency eval", ""]
    lines.append(
        f"Sample: {se2e['n']} questions from `{CORPUS_PATH}`. Wall-clock per "
        "`answer()` call (embed → retrieve → generate). Numbers are "
        "environment-specific (network + Gemini endpoint)."
    )
    lines.append("")
    lines.append("| Stage | p50 (ms) | p95 (ms) | mean (ms) |")
    lines.append("|---|---|---|---|")
    lines.append(
        f"| End-to-end answer | {se2e['p50']:.0f} | {se2e['p95']:.0f} | {se2e['mean']:.0f} |"
    )
    lines.append(
        f"| Generation only | {sgen['p50']:.0f} | {sgen['p95']:.0f} | {sgen['mean']:.0f} |"
    )

    md = "\n".join(lines) + "\n"
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(md, encoding="utf-8")
    print(md)
    print(f"Report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
