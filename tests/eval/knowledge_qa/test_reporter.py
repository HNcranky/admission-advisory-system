from eval.knowledge_qa.grader import CaseGrade
from eval.knowledge_qa.reporter import ModelReport, aggregate, render_report, verdict


def _grades(model, faithful, correct, cit, abst):
    """Build a uniform set of grades for a model from rate-like inputs."""
    return [
        CaseGrade(case_id=f"{model}-{i}", model=model, answered=True,
                  abstention_correct=a, faithful=f, correct=c, citation_f1=ci)
        for i, (f, c, ci, a) in enumerate(zip(faithful, correct, cit, abst))
    ]


def test_aggregate_computes_rates():
    grades = _grades("flash", faithful=[True, True], correct=[True, False],
                     cit=[1.0, 0.0], abst=[True, True])

    rep = aggregate(grades, "flash")

    assert isinstance(rep, ModelReport)
    assert rep.n_cases == 2
    assert rep.faithfulness_rate == 1.0
    assert rep.correctness_rate == 0.5
    assert rep.citation_f1_mean == 0.5
    assert rep.abstention_accuracy == 1.0


def test_verdict_pass_when_candidate_matches_within_tolerance():
    base = ModelReport(model="flash", n_cases=10, faithfulness_rate=0.9,
                       correctness_rate=0.9, citation_f1_mean=0.8, abstention_accuracy=0.95)
    cand = ModelReport(model="flash-lite", n_cases=10, faithfulness_rate=0.9,
                       correctness_rate=0.87, citation_f1_mean=0.78, abstention_accuracy=0.95)

    passed, _ = verdict(base, cand, tol=0.05)
    assert passed is True


def test_verdict_fails_on_faithfulness_regression():
    base = ModelReport(model="flash", n_cases=10, faithfulness_rate=0.9,
                       correctness_rate=0.9, citation_f1_mean=0.8, abstention_accuracy=0.95)
    cand = ModelReport(model="flash-lite", n_cases=10, faithfulness_rate=0.8,
                       correctness_rate=0.9, citation_f1_mean=0.8, abstention_accuracy=0.95)

    passed, reason = verdict(base, cand, tol=0.05)
    assert passed is False
    assert "faithful" in reason.lower()


def test_render_report_contains_models_and_verdict():
    base = ModelReport(model="gemini-2.5-flash", n_cases=2, faithfulness_rate=1.0,
                       correctness_rate=1.0, citation_f1_mean=1.0, abstention_accuracy=1.0)
    cand = ModelReport(model="gemini-2.5-flash-lite", n_cases=2, faithfulness_rate=1.0,
                       correctness_rate=1.0, citation_f1_mean=1.0, abstention_accuracy=1.0)

    md = render_report({"gemini-2.5-flash": base, "gemini-2.5-flash-lite": cand},
                       baseline="gemini-2.5-flash")

    assert "gemini-2.5-flash-lite" in md
    assert "Verdict" in md
