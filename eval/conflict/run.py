"""Run the synthetic conflict scenarios and write a detection/resolution report.

    python -m eval.conflict.run

Needs no database and no Gemini key: the conflict service is pure-deterministic.
"""

from pathlib import Path
from types import SimpleNamespace

from eval.conflict.scenarios import SCENARIOS, ConflictScenario
from services.conflict.comparison import compare
from services.conflict.detection import (
    detect_cutoff_conflicts,
    detect_quota_conflicts,
)
from services.conflict.resolution import resolve, resolve_cutoff_conflict

REPORT_PATH = Path("docs/superpowers/evals/conflict-synthetic.md")


def _detect(scenario: ConflictScenario):
    if scenario.field == "quota":
        return detect_quota_conflicts(scenario.candidates)
    return detect_cutoff_conflicts(scenario.candidates)


def _resolve(scenario: ConflictScenario, record):
    if scenario.field == "quota":
        report = compare(record.options)
        outcome = resolve(record, report)
        return outcome.status, outcome.decision_axes
    profile = SimpleNamespace(
        total_score=scenario.profile_score, admission_method="thpt_score"
    )
    outcome = resolve_cutoff_conflict(record, profile)
    return outcome.status, outcome.decision_axes


def main() -> None:
    rows = []
    tp = fp = fn = tn = 0
    for scenario in SCENARIOS:
        records = _detect(scenario)
        detected = len(records) > 0
        status = axes = None
        if detected:
            status, axes = _resolve(scenario, records[0])

        if scenario.should_conflict and detected:
            tp += 1
        elif scenario.should_conflict and not detected:
            fn += 1
        elif not scenario.should_conflict and detected:
            fp += 1
        else:
            tn += 1

        rows.append(
            {
                "key": scenario.key,
                "field": scenario.field,
                "should": scenario.should_conflict,
                "detected": detected,
                "status": status,
                "axes": ",".join(axes) if axes else "",
                "correct": detected == scenario.should_conflict,
            }
        )

    pos = tp + fn
    neg = fp + tn
    recall = tp / pos if pos else 0.0
    fp_rate = fp / neg if neg else 0.0

    lines = ["# Synthetic conflict-detection eval", ""]
    lines.append(
        "Controlled contradictions injected into the deterministic conflict "
        "service (`services/conflict/`). No LLM, no database."
    )
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Injected conflicts | {pos} |")
    lines.append(f"| Detection recall | {tp}/{pos} = {recall:.0%} |")
    lines.append(f"| Agreeing controls | {neg} |")
    lines.append(f"| False positives | {fp}/{neg} = {fp_rate:.0%} |")
    lines.append("")
    lines.append("## Per-scenario")
    lines.append("")
    lines.append("| Scenario | Field | Should conflict | Detected | Resolution | Decision axis | OK |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in rows:
        lines.append(
            f"| `{r['key']}` | {r['field']} | {'yes' if r['should'] else 'no'} | "
            f"{'yes' if r['detected'] else 'no'} | {r['status'] or '—'} | "
            f"{r['axes'] or '—'} | {'✅' if r['correct'] else '❌'} |"
        )

    md = "\n".join(lines) + "\n"
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(md, encoding="utf-8")
    print(md)
    print(f"Report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
