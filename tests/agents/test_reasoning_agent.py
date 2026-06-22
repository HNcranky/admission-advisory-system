from agents.reasoning_agent import reasoning_agent
from domain.models import CandidateProgram, CutoffEntry, Evidence, StudentProfile
from state import AgentState


def test_reasoning_agent_ranks_candidates():
    state = AgentState(user_query="test")
    state.student_profile = StudentProfile(
        total_score=27,
        subject_combination="A00",
        admission_method="thpt_score",
        preferred_majors=["computer_science"],
        preferred_schools=["hust"],
    )
    state.retrieved_programs = [
        CandidateProgram(
            candidate_id="hust:2026:computer_science:thpt_score",
            school_id="hust",
            school_name="Hanoi University of Science and Technology",
            admission_year=2026,
            program_id="computer_science",
            program_name="Khoa hoc May tinh",
            admission_method="thpt_score",
            subject_combinations=["A00", "A01"],
            evidence=[
                Evidence(
                    source_url="https://example.com",
                    school_name="HUST",
                    admission_year=2026,
                    field_name="record",
                    confidence_score=0.9,
                )
            ],
        )
    ]

    output = reasoning_agent(state)

    assert len(output.eligibility_checks) == 1
    assert len(output.ranked_recommendations) == 1
    assert output.ranked_recommendations[0].band in ("safe", "match")
    assert output.ranked_recommendations[0].score > 0


def test_reasoning_agent_marks_unknown_when_missing_critical():
    state = AgentState(user_query="test")
    state.student_profile = StudentProfile(
        preferred_majors=["computer_science"],
        missing_slots=["total_score", "subject_combination"],
    )
    state.retrieved_programs = [
        CandidateProgram(
            candidate_id="hust:2026:computer_science:thpt_score",
            school_id="hust",
            school_name="HUST",
            admission_year=2026,
            program_id="computer_science",
            program_name="Khoa hoc May tinh",
            admission_method="thpt_score",
            subject_combinations=["A00"],
        )
    ]

    output = reasoning_agent(state)

    assert output.ranked_recommendations[0].band == "unknown"


def test_uncertain_quota_candidate_is_not_safe_band():
    state = AgentState(
        user_query="Tu van",
        student_profile=StudentProfile(
            total_score=29, subject_combination="A00", admission_method="thpt_score"
        ),
        retrieved_programs=[
            CandidateProgram(
                candidate_id="vnu_uet:2026:cntt:thpt_score",
                school_id="vnu_uet",
                school_name="Dai hoc Cong nghe - DHQGHN",
                admission_year=2026,
                program_id="cntt",
                program_name="Cong nghe thong tin",
                admission_method="thpt_score",
                subject_combinations=["A00"],
                data_uncertain_fields=["quota"],
            )
        ],
    )

    output = reasoning_agent(state)

    assert output.ranked_recommendations[0].band != "safe"
    assert "Dữ liệu hạn ngạch chưa được xác minh giữa các nguồn." in output.ranked_recommendations[0].cautions


def _candidate(**overrides):
    base = dict(
        candidate_id="hust:2026:computer_science:thpt_score",
        school_id="hust",
        school_name="HUST",
        admission_year=2026,
        program_id="computer_science",
        program_name="Khoa hoc May tinh",
        admission_method="thpt_score",
        subject_combinations=["A00", "A01"],
    )
    base.update(overrides)
    return CandidateProgram(**base)


def test_ec12_wrong_combination_is_not_ranked_and_flagged_not_eligible():
    """EC-12: điểm cao nhưng tổ hợp D01 không được nhận → NOT_ELIGIBLE,
    không xuất hiện trong recommendations, không tính score-fit."""
    state = AgentState(user_query="test")
    state.student_profile = StudentProfile(
        total_score=28.0, subject_combination="D01", admission_method="thpt_score",
        preferred_majors=["computer_science"], preferred_schools=["hust"],
    )
    state.retrieved_programs = [_candidate()]

    output = reasoning_agent(state)

    assert output.ranked_recommendations == []          # KHÔNG được xếp hạng
    assert len(output.eligibility_checks) == 1
    check = output.eligibility_checks[0]
    assert check.eligible is False
    assert "D01" in check.risks[0]
    assert "A00" in check.risks[0]                       # nêu rõ tổ hợp được nhận


def test_method_mismatch_still_ranked_with_caution_no_score_fit():
    """Row khác phương thức: vẫn xếp theo ngành/trường, caution rõ ràng,
    KHÔNG check tổ hợp, KHÔNG cộng điểm score-fit."""
    state = AgentState(user_query="test")
    state.student_profile = StudentProfile(
        total_score=28.0, subject_combination="D01", admission_method="thpt_score",
        preferred_majors=["computer_science"], preferred_schools=["hust"],
    )
    # Row ĐGNL — tổ hợp D01 không nằm trong list nhưng row này KHÔNG bị NOT_ELIGIBLE
    state.retrieved_programs = [_candidate(
        candidate_id="hust:2026:computer_science:competency",
        admission_method="Đánh giá tư duy (TSA)",
    )]

    output = reasoning_agent(state)

    assert len(output.ranked_recommendations) == 1
    rec = output.ranked_recommendations[0]
    assert rec.score == 0.5                              # 0.35 ngành + 0.15 trường
    assert any("khác phương thức" in c for c in rec.cautions)
    assert output.eligibility_checks[0].eligible is None


def test_score_bonus_not_applied_for_competency_method():
    """EC-13: điểm ĐGNL không so được với heuristic thang 30 → không bonus + caution."""
    state = AgentState(user_query="test")
    state.student_profile = StudentProfile(
        total_score=105.0, subject_combination="A00", admission_method="competency_test",
        preferred_majors=["computer_science"],
    )
    state.retrieved_programs = [_candidate(admission_method="competency_test")]

    output = reasoning_agent(state)

    rec = output.ranked_recommendations[0]
    assert rec.score == 0.75                             # 0.40 tổ hợp + 0.35 ngành, KHÔNG +0.10
    assert any("chưa thể đối chiếu" in c for c in rec.cautions)


def test_score_bonus_skipped_with_caution_when_method_unknown():
    """EC-13 defense-in-depth: gọi pipeline trực tiếp không có phương thức."""
    state = AgentState(user_query="test")
    state.student_profile = StudentProfile(
        total_score=27.0, subject_combination="A00",
        preferred_majors=["computer_science"],
    )
    state.retrieved_programs = [_candidate()]

    output = reasoning_agent(state)

    rec = output.ranked_recommendations[0]
    assert rec.score == 0.75                             # không +0.10 vì method unknown
    assert any("chưa rõ phương thức" in c for c in rec.cautions)


def _hist(*pairs, source="https://ts.hust.edu.vn/dc", trust=5):
    return [
        CutoffEntry(cutoff_year=y, admission_method="thpt_score", cutoff_score=s,
                    score_scale=30.0, source_url=source, trust_level=trust)
        for (y, s) in pairs
    ]


def _profile_27():
    return StudentProfile(
        total_score=27.0, subject_combination="A00", admission_method="thpt_score",
        preferred_majors=["computer_science"], preferred_schools=["hust"],
    )


def test_margin_bonus_replaces_absolute_threshold():
    """Có cutoff: margin 1.5 → +0.10 với reason nêu năm tham chiếu (không dùng heuristic 26/24)."""
    state = AgentState(user_query="test")
    state.student_profile = _profile_27()
    state.retrieved_programs = [_candidate(cutoff_history=_hist((2025, 25.5)))]

    output = reasoning_agent(state)

    rec = output.ranked_recommendations[0]
    assert rec.score == 1.0                               # 0.40+0.35+0.15+0.10
    assert any("tham chiếu 2025" in r for r in rec.reasons)
    assert rec.cutoff_assessment is not None and rec.cutoff_assessment.score_fit == "above"


def test_small_positive_margin_gets_half_bonus():
    state = AgentState(user_query="test")
    state.student_profile = _profile_27()
    state.retrieved_programs = [_candidate(cutoff_history=_hist((2025, 26.5)))]  # margin +0.5

    output = reasoning_agent(state)

    assert output.ranked_recommendations[0].score == 0.95  # +0.05


def test_ec14_borderline_caps_band_at_match_with_caution():
    state = AgentState(user_query="test")
    state.student_profile = StudentProfile(
        total_score=26.25, subject_combination="A01", admission_method="thpt_score",
        preferred_majors=["computer_science"], preferred_schools=["hust"],
    )
    state.retrieved_programs = [
        _candidate(subject_combinations=["A00", "A01"], cutoff_history=_hist((2025, 26.20)))
    ]

    output = reasoning_agent(state)

    rec = output.ranked_recommendations[0]
    assert rec.band == "match"                            # 0.90 → "safe" nếu không cap
    assert any("sát ngưỡng tham chiếu 2025" in c.lower() for c in rec.cautions)
    assert rec.cutoff_assessment.score_fit == "borderline"


def test_below_reference_caps_band_at_reach():
    state = AgentState(user_query="test")
    state.student_profile = _profile_27()
    state.retrieved_programs = [_candidate(cutoff_history=_hist((2025, 28.0)))]  # margin −1.0

    output = reasoning_agent(state)

    rec = output.ranked_recommendations[0]
    assert rec.band == "reach"
    assert any("thấp hơn mức tham chiếu 2025" in c.lower() for c in rec.cautions)


def test_ec15_volatile_history_caps_match_with_range_caution():
    state = AgentState(user_query="test")
    state.student_profile = StudentProfile(
        total_score=26.4, subject_combination="A00", admission_method="thpt_score",
        preferred_majors=["computer_science"], preferred_schools=["hust"],
    )
    state.retrieved_programs = [
        _candidate(cutoff_history=_hist((2023, 24.8), (2024, 26.7), (2025, 25.9)))
    ]

    output = reasoning_agent(state)

    rec = output.ranked_recommendations[0]
    assert rec.band == "match"
    assert any("dao động 24.8–26.7" in c for c in rec.cautions)
    assert rec.cutoff_assessment.score_fit == "uncertain"


def test_ec16_decision_changing_marks_uncertain_and_dual_caution():
    state = AgentState(user_query="test")
    state.student_profile = StudentProfile(
        total_score=26.5, subject_combination="A00", admission_method="thpt_score",
        preferred_majors=["computer_science"], preferred_schools=["hust"],
    )
    history = _hist((2025, 26.2), trust=4) + _hist((2025, 26.8), source="https://dhqg/dc", trust=5)
    state.retrieved_programs = [_candidate(cutoff_history=history)]

    output = reasoning_agent(state)

    rec = output.ranked_recommendations[0]
    candidate = output.retrieved_programs[0]
    assert "cutoff_score" in candidate.data_uncertain_fields
    assert rec.band == "reach"                            # nhãn bảo thủ below → cap reach
    assert any("các nguồn ghi khác nhau về điểm chuẩn" in c.lower() for c in rec.cautions)
    # caution một-nguồn ("thấp hơn mức tham chiếu") bị THAY bằng dual note:
    assert not any("thấp hơn mức tham chiếu" in c.lower() for c in rec.cautions)


def test_no_history_falls_back_to_absolute_threshold():
    state = AgentState(user_query="test")
    state.student_profile = _profile_27()
    state.retrieved_programs = [_candidate()]

    output = reasoning_agent(state)

    rec = output.ranked_recommendations[0]
    assert rec.score == 1.0                               # heuristic cũ: 27 >= 26 → +0.10
    assert rec.cutoff_assessment is None
