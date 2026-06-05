from agents.models import CandidateProgram, CutoffAssessment, CutoffEntry, RankedRecommendation


def test_cutoff_entry_minimal():
    e = CutoffEntry(
        cutoff_year=2025, admission_method="thpt_score",
        cutoff_score=28.25, source_url="https://ts.hust.edu.vn/x",
    )
    assert e.score_scale is None and e.trust_level is None and e.note is None


def test_candidate_program_defaults_empty_cutoff_history():
    c = CandidateProgram(
        candidate_id="hust:2026:cs:thpt_score", school_id="hust", school_name="HUST",
        admission_year=2026, program_name="KHMT",
    )
    assert c.cutoff_history == []


def test_ranked_recommendation_accepts_assessment():
    a = CutoffAssessment(score_fit="borderline", reference_year=2025, margin=0.05)
    r = RankedRecommendation(
        candidate_id="c", band="match", score=0.6, summary="s", cutoff_assessment=a,
    )
    assert r.cutoff_assessment.score_fit == "borderline"
    assert r.cutoff_assessment.latest_values == []
