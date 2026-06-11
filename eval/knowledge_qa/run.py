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
