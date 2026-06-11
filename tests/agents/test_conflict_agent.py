from agents.conflict_agent import conflict_agent
from agents.models import CandidateProgram, CutoffEntry, Evidence, StudentProfile
from state import AgentState


def candidate(source_url, quota, trust):
    return CandidateProgram(
        candidate_id="vnu_uet:2026:cntt:thpt_score",
        school_id="vnu_uet",
        school_name="Dai hoc Cong nghe - DHQGHN",
        admission_year=2026,
        program_id="cntt",
        program_name="Cong nghe thong tin",
        admission_method="thpt_score",
        quota={"value": quota, "unit": "students"},
        evidence=[
            Evidence(
                source_url=source_url,
                school_name="Dai hoc Cong nghe - DHQGHN",
                admission_year=2026,
                field_name="quota",
                normalized_value={"value": quota, "unit": "students"},
                trust_level=trust,
                confidence_score=0.9,
            )
        ],
    )


def test_conflict_agent_resolves_decisive_quota_conflict():
    state = AgentState(
        user_query="Tu van",
        retrieved_programs=[
            candidate("mock://uet/program-page", 120, 2),
            candidate("mock://vnu/proposal-pdf", 150, 3),
        ],
    )

    output = conflict_agent(state)

    assert len(output.conflict_records) == 1
    assert len(output.resolution_outcomes) == 1
    assert output.resolution_outcomes[0].status == "resolved"
    assert output.resolution_outcomes[0].resolved_value == 150
    assert output.conflicts == []


def test_conflict_agent_tie_resolves_unresolved_and_marks_uncertain():
    state = AgentState(
        user_query="Tu van",
        retrieved_programs=[
            candidate("mock://a", 120, 2),
            candidate("mock://b", 150, 2),
        ],
    )

    output = conflict_agent(state)

    assert output.resolution_outcomes[0].status == "unresolved"
    assert output.conflicts
    assert any(
        "quota" in cand.data_uncertain_fields for cand in output.retrieved_programs
    )


def _cutoff_state(total_score, values_by_source, trusts=(4, 5)):
    history = [
        CutoffEntry(cutoff_year=2025, admission_method="thpt_score", cutoff_score=v,
                    score_scale=30.0, source_url=u, trust_level=t)
        for (u, v), t in zip(values_by_source.items(), trusts)
    ]
    return AgentState(
        user_query="Tu van",
        student_profile=StudentProfile(total_score=total_score, admission_method="thpt_score"),
        retrieved_programs=[
            CandidateProgram(
                candidate_id="hust:2026:computer_science:thpt_score", school_id="hust",
                school_name="HUST", admission_year=2026, program_id="computer_science",
                program_name="Khoa hoc May tinh", admission_method="thpt_score",
                cutoff_history=history,
            )
        ],
    )


def test_cutoff_decision_changing_is_unresolved_marks_uncertain_no_llm():
    # 26.5 nằm giữa 26.2 (above) và 26.8 (below) → decision-changing (EC-16).
    state = _cutoff_state(26.5, {"https://truong/dc": 26.2, "https://dhqg/dc": 26.8})
    output = conflict_agent(state)

    outcome = output.resolution_outcomes[0]
    assert outcome.field_name == "cutoff_score"
    assert outcome.status == "unresolved"
    assert outcome.used_llm_tiebreaker is False
    assert "26.2" in outcome.rationale and "26.8" in outcome.rationale
    assert "cutoff_score" in output.retrieved_programs[0].data_uncertain_fields
    assert output.conflicts                                # nuôi policy flag retrieval_conflicts_detected


def test_cutoff_same_label_resolves_by_trust_with_full_rationale():
    # 28.0 trên cả 25.0 lẫn 25.2 → cùng nhãn above → resolved theo trust cao nhất (25.2, trust 5).
    state = _cutoff_state(28.0, {"https://truong/dc": 25.0, "https://dhqg/dc": 25.2})
    output = conflict_agent(state)

    outcome = output.resolution_outcomes[0]
    assert outcome.status == "resolved"
    assert outcome.resolved_value == 25.2
    assert "25" in outcome.rationale and len(outcome.rejected_evidence) == 1
    assert "cutoff_score" not in output.retrieved_programs[0].data_uncertain_fields


def test_cutoff_without_profile_score_resolves_by_trust():
    state = _cutoff_state(26.5, {"https://truong/dc": 26.2, "https://dhqg/dc": 26.8})
    state.student_profile = StudentProfile()              # thiếu điểm → không phân loại được
    output = conflict_agent(state)

    assert output.resolution_outcomes[0].status == "resolved"
