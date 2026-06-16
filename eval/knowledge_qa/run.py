import os
import time
from pathlib import Path

from eval.knowledge_qa.gateways import build_judge_gateway
from eval.knowledge_qa.golden_set import load_golden_set
from eval.knowledge_qa.grader import _answered, grade_case
from eval.knowledge_qa.reporter import aggregate, render_report
from eval.knowledge_qa.runner import run_case

MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
BASELINE = "gemini-2.5-flash"
REPORT_PATH = Path("docs/superpowers/evals/2026-06-10-knowledge-qa-flash-vs-flash-lite.md")

# Each case fires several Gemini calls (generation per model + a flash judge per
# answerable case). On a rate-limited free-tier key pool an unthrottled burst
# trips per-key cooldowns, and a call that fails then degrades silently — a
# failed generation looks like "no answer" and a failed judge returns null,
# both of which corrupt the metrics. A small inter-call delay keeps keys under
# their RPM; retry-with-wait absorbs the residual short-window exhaustions so
# every case gets a real generation AND a real grade. The numbers then reflect
# the models, not the rate limiter. Tune via the env vars below.
CALL_DELAY_SECONDS = float(os.getenv("EVAL_CALL_DELAY_SECONDS", "2.0"))
RETRY_ATTEMPTS = int(os.getenv("EVAL_RETRY_ATTEMPTS", "5"))
RETRY_WAIT_SECONDS = float(os.getenv("EVAL_RETRY_WAIT_SECONDS", "65"))


def _generate(case, model):
    """Generate, retrying when an answerable case comes back empty — that almost
    always means the call was rate-limited (our golden answerable chunks support
    a real answer), not that the model genuinely declined. Abstain cases are
    expected to be empty, so they never retry."""
    result = run_case(case, model)
    for _ in range(RETRY_ATTEMPTS - 1):
        if case.abstain or _answered(result):
            return result
        time.sleep(RETRY_WAIT_SECONDS)
        result = run_case(case, model)
    return result


def _grade(case, result, model, judge):
    """Grade, retrying when the flash judge fails on an answered answerable case
    (it returns faithful=None then), so a rate-limited judge call doesn't drop
    the case from the faithfulness/correctness sample."""
    grade = grade_case(case, result, model, judge)
    for _ in range(RETRY_ATTEMPTS - 1):
        if case.abstain or not grade.answered or grade.faithful is not None:
            return grade
        time.sleep(RETRY_WAIT_SECONDS)
        grade = grade_case(case, result, model, judge)
    return grade


def main() -> None:
    cases = load_golden_set()
    judge = build_judge_gateway()
    grades = {m: [] for m in MODELS}

    for case in cases:
        for model in MODELS:
            result = _generate(case, model)
            grades[model].append(_grade(case, result, model, judge))
            if CALL_DELAY_SECONDS:
                time.sleep(CALL_DELAY_SECONDS)

    reports = {m: aggregate(grades[m], m) for m in MODELS}
    md = render_report(reports, baseline=BASELINE)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(md, encoding="utf-8")
    print(md)
    print(f"\nReport written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
