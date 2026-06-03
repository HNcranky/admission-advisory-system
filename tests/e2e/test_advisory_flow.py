import agents.conflict_agent as conflict_agent_module
import agents.profile_agent as profile_agent_module
import agents.policy_agent as policy_agent_module
import agents.retrieval_agent as retrieval_agent
from agents.models import CandidateProgram, Evidence, StudentProfile
from graph import graph
from services.conflict.models import ConflictRecord, EvidenceOption
from services.inference.models import InferenceResult
from state import AgentState


def _mock_candidates():
    return [
        CandidateProgram(
            candidate_id="hust:2026:computer_science:thpt_score",
            school_id="hust",
            school_name="HUST",
            admission_year=2026,
            program_id="computer_science",
            program_name="Khoa hoc May tinh",
            admission_method="thpt_score",
            subject_combinations=["A00", "A01"],
            evidence=[
                Evidence(
                    source_url="https://example.com/hust-cs",
                    school_name="HUST",
                    admission_year=2026,
                    field_name="record",
                )
            ],
        ),
        CandidateProgram(
            candidate_id="hust:2026:software_engineering:thpt_score",
            school_id="hust",
            school_name="HUST",
            admission_year=2026,
            program_id="software_engineering",
            program_name="Ky thuat phan mem",
            admission_method="thpt_score",
            subject_combinations=["A00", "A01"],
            evidence=[
                Evidence(
                    source_url="https://example.com/hust-se",
                    school_name="HUST",
                    admission_year=2026,
                    field_name="record",
                )
            ],
        ),
    ]


def _mock_profile():
    return StudentProfile(
        total_score=27,
        subject_combination="A00",
        preferred_majors=["computer_science"],
        preferred_schools=["hust"],
        missing_slots=[],
    )


def test_advisory_flow_returns_policy_checked_answer(monkeypatch):
    monkeypatch.setattr(
        profile_agent_module,
        "build_profile_with_gateway",
        lambda user_query, gateway: _mock_profile(),
    )
    monkeypatch.setattr(
        retrieval_agent,
        "fetch_candidates",
        lambda filters, limit=100: _mock_candidates(),
    )

    state = AgentState(
        user_query="Em duoc 27 diem A00 muon hoc Cong nghe thong tin o HUST",
        admission_year=2026,
    )
    result = graph.invoke(state)

    assert result["final_answer"]
    assert "Hồ sơ hiện tại" in result["final_answer"]
    assert result["uncertainty_reasons"] == []

    policy = result.get("policy_decision")
    assert policy is not None
    assert policy.allow_answer is True
    assert policy.requires_follow_up is False


def test_advisory_flow_surfaces_uncertainty_for_policy_ambiguity(monkeypatch):
    class FakeGateway:
        def __init__(self):
            self.requests = []

        def run(self, request):
            self.requests.append(request)
            return InferenceResult(
                agent_name=request.agent_name,
                model="gemini-2.5-flash",
                provider="fake",
                content=(
                    '{"warnings":["Ambiguous quota wording."],'
                    '"requires_human_verification":true}'
                ),
                parsed_data={
                    "warnings": ["Ambiguous quota wording."],
                    "requires_human_verification": True,
                },
            )

    fake_gateway = FakeGateway()

    monkeypatch.setattr(
        profile_agent_module,
        "build_profile_with_gateway",
        lambda user_query, gateway: _mock_profile(),
    )
    monkeypatch.setattr(
        retrieval_agent,
        "fetch_candidates",
        lambda filters, limit=100: _mock_candidates(),
    )
    monkeypatch.setattr(
        conflict_agent_module,
        "detect_quota_conflicts",
        lambda candidates: [
            ConflictRecord(
                conflict_key="hust:2026:computer_science:thpt_score",
                field_name="quota",
                school_id="hust",
                school_name="HUST",
                admission_year=2026,
                program_id="computer_science",
                program_name="Khoa hoc May tinh",
                admission_method="thpt_score",
                options=[
                    EvidenceOption(
                        evidence_id="mock://a|quota",
                        source_url="mock://a",
                        trust_level=2,
                        confidence_score=0.9,
                        value=120,
                    ),
                    EvidenceOption(
                        evidence_id="mock://b|quota",
                        source_url="mock://b",
                        trust_level=2,
                        confidence_score=0.9,
                        value=150,
                    ),
                ],
            )
        ],
    )
    monkeypatch.setattr(policy_agent_module, "build_default_gateway", lambda: fake_gateway)

    state = AgentState(
        user_query="Em duoc 27 diem A00 muon hoc Cong nghe thong tin o HUST",
        admission_year=2026,
    )
    result = graph.invoke(state)

    policy = result["policy_decision"]
    assert "retrieval_conflicts_detected" in policy.policy_flags
    assert "Ambiguous quota wording." in policy.warnings
    assert result["uncertainty_reasons"] == ["policy_ambiguity_requires_verification"]

    assert len(fake_gateway.requests) == 1
    assert fake_gateway.requests[0].agent_name == "policy_agent"
    assert fake_gateway.requests[0].task_type == "policy_ambiguity"


def test_advisory_flow_handles_empty_retrieval(monkeypatch):
    monkeypatch.setattr(
        profile_agent_module,
        "build_profile_with_gateway",
        lambda user_query, gateway: _mock_profile(),
    )
    monkeypatch.setattr(retrieval_agent, "fetch_candidates", lambda filters, limit=100: [])

    state = AgentState(
        user_query="Em duoc 27 diem A00 muon hoc Cong nghe thong tin o HUST",
        admission_year=2026,
    )
    result = graph.invoke(state)

    assert "Chưa có đề xuất phù hợp" in result["final_answer"]
    assert result["policy_decision"] is not None
    assert "empty_retrieval" in result["policy_decision"].policy_flags


def test_graph_mock_retrieval_conflict_reaches_final_answer(monkeypatch):
    monkeypatch.setenv("ADVISORY_MOCK_CONFLICTS", "1")

    def fail_get_cursor(*args, **kwargs):
        raise AssertionError("DB should not be used by retrieval in mock mode")

    monkeypatch.setattr("services.retrieval_service.get_cursor", fail_get_cursor)
    monkeypatch.setattr(
        profile_agent_module,
        "build_profile_with_gateway",
        lambda user_query, gateway: StudentProfile(
            total_score=27,
            subject_combination="A00",
            preferred_majors=["cntt"],
            preferred_schools=["vnu_uet"],
            missing_slots=[],
        ),
    )

    result = graph.invoke(
        AgentState(user_query="Tu van nganh CNTT UET nam 2026").model_dump()
    )

    assert "final_answer" in result
    assert "Xác minh dữ liệu" in result["final_answer"]
