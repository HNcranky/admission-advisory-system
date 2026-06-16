import agents.conflict_agent as conflict_agent_module
import agents.profile_agent as profile_agent_module
import agents.policy_agent as policy_agent_module
import agents.retrieval_agent as retrieval_agent
from agents.models import CandidateProgram, CutoffEntry, Evidence, StudentProfile
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
        admission_method="thpt_score",
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
    assert "Dựa trên hồ sơ hiện tại của bạn" in result["final_answer"]
    assert "### 1." in result["final_answer"]
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

    assert "chưa tìm thấy chương trình đáp ứng đồng thời" in result["final_answer"]
    assert "tổ hợp A00" in result["final_answer"]
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
    assert "**Lưu ý dữ liệu:**" in result["final_answer"]


def _cutoff_profile(total_score):
    return StudentProfile(
        total_score=total_score, admission_method="thpt_score", subject_combination="A00",
        preferred_majors=["computer_science"], preferred_schools=["hust"], missing_slots=[],
    )


def _cutoff_candidate(history):
    return CandidateProgram(
        candidate_id="hust:2026:computer_science:thpt_score", school_id="hust",
        school_name="HUST", admission_year=2026, program_id="computer_science",
        program_name="Khoa hoc May tinh", admission_method="thpt_score",
        subject_combinations=["A00", "A01"],
        evidence=[Evidence(source_url="https://example.com/hust-cs", school_name="HUST",
                           admission_year=2026, field_name="record")],
        cutoff_history=history,
    )


def _ch(year, score, source="https://ts.hust.edu.vn/dc", trust=5):
    return CutoffEntry(cutoff_year=year, admission_method="thpt_score", cutoff_score=score,
                       score_scale=30.0, source_url=source, trust_level=trust)


def _run_cutoff_flow(monkeypatch, total_score, history):
    monkeypatch.setattr(
        profile_agent_module, "build_profile_with_gateway",
        lambda user_query, gateway: _cutoff_profile(total_score),
    )
    monkeypatch.setattr(
        retrieval_agent, "fetch_candidates",
        lambda filters, limit=100: [_cutoff_candidate(history)],
    )
    state = AgentState(user_query="Em muon hoc CNTT o HUST", admission_year=2026)
    return graph.invoke(state)


def test_ec14_borderline_score_never_asserted_safe(monkeypatch):
    """EC-14: 26.25 vs cutoff 26.20 (+0.05) → sát ngưỡng, không nhãn an toàn."""
    result = _run_cutoff_flow(monkeypatch, 26.25, [_ch(2025, 26.20)])

    answer = result["final_answer"]
    assert "sát ngưỡng tham chiếu 2025" in answer.lower()
    assert "**Mức phù hợp: Cao / An toàn**" not in answer
    assert "no_admission_assertion_on_reference_cutoff" in result["policy_decision"].blocked_claims


def test_ec15_volatile_cutoffs_warn_and_stay_uncertain(monkeypatch):
    """EC-15: 24.8/26.7/25.9 → cảnh báo biến động, không kết luận."""
    result = _run_cutoff_flow(
        monkeypatch, 26.4, [_ch(2023, 24.8), _ch(2024, 26.7), _ch(2025, 25.9)],
    )

    answer = result["final_answer"]
    assert "dao động 24.8–26.7" in answer
    assert "chưa thể kết luận" in answer
    assert "**Mức phù hợp: Cao / An toàn**" not in answer


def test_ec16_conflicting_cutoffs_show_both_sources_no_single_verdict(monkeypatch):
    """EC-16: 26.2 vs 26.8, điểm 26.5 → hiện CẢ HAI giá trị, nhãn thận trọng, conflict flag."""
    history = [
        _ch(2025, 26.2, source="https://truong.example/dc", trust=4),
        _ch(2025, 26.8, source="https://dhqg.example/dc", trust=5),
    ]
    result = _run_cutoff_flow(monkeypatch, 26.5, history)

    answer = result["final_answer"]
    assert "26.2" in answer and "26.8" in answer
    assert "các nguồn ghi khác nhau về điểm chuẩn" in answer.lower()
    assert "**Mức phù hợp: Cần cân nhắc**" in answer       # nhãn bảo thủ (below → reach)
    assert "retrieval_conflicts_detected" in result["policy_decision"].policy_flags


def test_ec18_reference_year_caveat_always_present_with_cutoff_data(monkeypatch):
    """EC-18: dùng cutoff lịch sử → caveat năm tham chiếu, không khẳng định 2026."""
    result = _run_cutoff_flow(monkeypatch, 28.0, [_ch(2025, 26.5)])

    answer = result["final_answer"]
    assert "Chưa có điểm chuẩn chính thức cho kỳ tuyển sinh năm 2026" in answer
    assert "dữ liệu năm 2025 làm tham chiếu" in answer
    assert "Điểm chuẩn tham chiếu 2025" in answer
    assert "historical_cutoff_reference" in result["policy_decision"].policy_flags
