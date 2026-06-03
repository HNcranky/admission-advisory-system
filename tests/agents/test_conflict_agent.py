import agents.conflict_agent as conflict_agent_module
from agents.conflict_agent import conflict_agent
from agents.models import CandidateProgram, Evidence
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


def _conflicting_state():
    """Two sources disagree on quota for the same program/method (non-decisive tie)."""
    def candidate(evidence_id, quota, trust):
        return CandidateProgram(
            candidate_id=f"hust:2026:computer_science:thpt_score",
            school_id="hust",
            school_name="HUST",
            admission_year=2026,
            program_id="computer_science",
            program_name="Khoa hoc May tinh",
            admission_method="thpt_score",
            quota={"value": quota},
            evidence=[
                Evidence(
                    source_url=f"https://src-{evidence_id}.test",
                    school_name="HUST",
                    admission_year=2026,
                    field_name="quota",
                    trust_level=trust,
                )
            ],
        )

    # Same trust_level on both -> deterministic comparison is NOT decisive.
    return AgentState(
        user_query="q",
        retrieved_programs=[candidate("a", 120, 5), candidate("b", 150, 5)],
    )


def test_conflict_agent_resolves_via_llm_tiebreaker(monkeypatch):
    class _Gateway:
        def is_available(self):
            return True

    monkeypatch.setattr(conflict_agent_module, "build_default_gateway", lambda: _Gateway())

    def fake_tiebreak(record, report, gateway):
        chosen = report.ranked_options[0].source_url
        return {"confidence": "high", "chosen_source_url": chosen, "rationale": "nguon dang tin nhat"}

    monkeypatch.setattr(conflict_agent_module, "interpret_conflict_tiebreak", fake_tiebreak)

    state = conflict_agent(_conflicting_state())

    assert any(o.used_llm_tiebreaker and o.status == "resolved" for o in state.resolution_outcomes)


def test_conflict_agent_marks_unresolved_candidates_uncertain(monkeypatch):
    class _UnavailableGateway:
        def is_available(self):
            return False

    monkeypatch.setattr(conflict_agent_module, "build_default_gateway", lambda: _UnavailableGateway())

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
        "quota" in candidate.data_uncertain_fields
        for candidate in output.retrieved_programs
    )
