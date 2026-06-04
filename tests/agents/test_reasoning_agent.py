from agents.reasoning_agent import reasoning_agent
from agents.models import CandidateProgram, Evidence, StudentProfile
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
