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
    candidates = [m for m in reports if m != baseline]

    lines = [
        "# Knowledge-QA model-tier eval",
        "",
        f"Baseline: `{baseline}` · Candidates: "
        + ", ".join(f"`{m}`" for m in candidates)
        + f" · Cases: {base.n_cases}",
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

    lines += ["", "## Verdict per candidate", ""]
    for cand_name in candidates:
        passed, reason = verdict(base, reports[cand_name], tol=tol)
        tag = "PASS — safe to adopt" if passed else "FAIL — regresses vs baseline"
        lines.append(f"- **`{cand_name}`** — {tag}. {reason}")
    lines.append("")
    return "\n".join(lines)
