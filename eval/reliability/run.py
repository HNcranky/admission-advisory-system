"""Run the reliability scenarios and print/write a recovery report.

    python -m eval.reliability.run

Needs no database and no Gemini key: the provider is mocked, the gateway is real.
"""

from collections import defaultdict
from pathlib import Path

from eval.reliability.scenarios import SCENARIOS, run_scenario

REPORT_PATH = Path("docs/superpowers/evals/reliability-gateway.md")

_FAMILY_LABEL = {
    "api_fallback": "Fallback recovery (hard API failure)",
    "structured_output": "Structured-output recovery (malformed JSON)",
    "degradation_contract": "Graceful-degradation contract (no fallback)",
}


def main() -> None:
    results = [run_scenario(s) for s in SCENARIOS]

    by_family = defaultdict(list)
    for (recovered, detail), scenario in zip(results, SCENARIOS):
        by_family[scenario.family].append((recovered, detail))

    lines = ["# Inference-gateway reliability eval", ""]
    lines.append(
        "Synthetic failure injection against the real `LLMGateway.run` "
        "(provider mocked, no network). Each scenario = one scripted failure mode."
    )
    lines.append("")
    lines.append("| Family | Scenarios | Recovered | Rate |")
    lines.append("|---|---|---|---|")

    overall_ok = overall_n = 0
    for family, label in _FAMILY_LABEL.items():
        rows = by_family.get(family, [])
        if not rows:
            continue
        ok = sum(1 for recovered, _ in rows if recovered)
        n = len(rows)
        overall_ok += ok
        overall_n += n
        rate = f"{ok / n:.0%}" if n else "—"
        lines.append(f"| {label} | {n} | {ok} | {rate} |")

    rate = f"{overall_ok / overall_n:.0%}" if overall_n else "—"
    lines.append(f"| **All** | {overall_n} | {overall_ok} | **{rate}** |")
    lines.append("")
    lines.append("## Per-scenario detail")
    lines.append("")
    lines.append("| Scenario | Provider calls | Used fallback | Outcome | Recovered |")
    lines.append("|---|---|---|---|---|")
    for recovered, detail in results:
        outcome = detail["error"] or detail["result_failure_type"] or "clean result"
        lines.append(
            f"| `{detail['key']}` | {detail['provider_calls']} | "
            f"{'yes' if detail['used_fallback'] else 'no'} | {outcome} | "
            f"{'✅' if recovered else '❌'} |"
        )

    md = "\n".join(lines) + "\n"
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(md, encoding="utf-8")
    print(md)
    print(f"Report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
