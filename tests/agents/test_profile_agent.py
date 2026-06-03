import agents.profile_agent as profile_agent_module
from agents.models import StudentProfile
from services.inference.models import InferenceResult
from state import AgentState


def test_profile_agent_extracts_score_combo_and_major(monkeypatch):
    monkeypatch.setattr(
        profile_agent_module,
        "build_profile_with_gateway",
        lambda user_query, gateway: StudentProfile(
            total_score=27,
            subject_combination="A00",
            preferred_majors=["computer_science"],
            preferred_schools=["hust"],
            missing_slots=[],
        ),
    )
    monkeypatch.setattr(profile_agent_module, "build_default_gateway", lambda: object())

    state = AgentState(
        user_query="Em duoc 27 diem A00 muon hoc Cong nghe thong tin o HUST",
        admission_year=2026,
    )

    output = profile_agent_module.profile_agent(state)

    assert output.student_profile.total_score == 27
    assert output.student_profile.subject_combination == "A00"
    assert "computer_science" in output.student_profile.preferred_majors
    assert "hust" in output.student_profile.preferred_schools


def test_profile_agent_marks_missing_slots(monkeypatch):
    monkeypatch.setattr(
        profile_agent_module,
        "build_profile_with_gateway",
        lambda user_query, gateway: StudentProfile(
            preferred_majors=["economics"],
            missing_slots=["total_score", "subject_combination"],
        ),
    )
    monkeypatch.setattr(profile_agent_module, "build_default_gateway", lambda: object())

    state = AgentState(user_query="Em muon hoc nganh kinh te", admission_year=2026)

    output = profile_agent_module.profile_agent(state)

    assert "total_score" in output.student_profile.missing_slots
    assert "subject_combination" in output.student_profile.missing_slots


class FakeGateway:
    def run(self, request):
        return InferenceResult(
            agent_name=request.agent_name,
            model="gemini-2.5-flash-lite",
            provider="fake",
            content='{"preferred_majors":["economics"],"missing_slots":["total_score"]}',
            parsed_data={
                "preferred_majors": ["economics"],
                "missing_slots": ["total_score"],
            },
        )


def test_profile_agent_uses_injected_gateway():
    state = AgentState(user_query="Em muon hoc nganh kinh te", admission_year=2026)

    output = profile_agent_module.profile_agent(state, gateway=FakeGateway())

    # missing_slots is now recomputed from the slot registry critical set, so it
    # reflects every unfilled critical slot (admission_year lives on AgentState,
    # not StudentProfile, so it always reads as missing here).
    assert output.student_profile == StudentProfile(
        preferred_majors=["economics"],
        missing_slots=["admission_year", "total_score", "subject_combination"],
    )
    assert output.retrieval_missing_data == ["admission_year", "total_score", "subject_combination"]

def test_profile_agent_reuses_seeded_student_profile(monkeypatch):
    seeded = StudentProfile(
        total_score=27.0,
        preferred_majors=["computer_science"],
        location_preference="Ha Noi",
        missing_slots=[],
    )

    monkeypatch.setattr(
        profile_agent_module,
        "build_profile_with_gateway",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected call")),
    )

    state = AgentState(
        user_query="ignored",
        admission_year=2026,
        student_profile=seeded,
        profile_seeded=True,
    )

    result = profile_agent_module.profile_agent(state)

    assert result.student_profile == seeded
    assert result.retrieval_missing_data == []