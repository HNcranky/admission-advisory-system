from agents.models import StudentProfile
from agents.retrieval_agent import retrieval_agent
from services.mock_retrieval import (
    build_mock_conflict_candidates,
    mock_conflicts_enabled,
)
import services.retrieval_service as retrieval_service
from state import AgentState


def test_mock_conflicts_enabled_defaults_false(monkeypatch):
    monkeypatch.delenv("ADVISORY_MOCK_CONFLICTS", raising=False)
    assert mock_conflicts_enabled() is False


def test_mock_conflicts_enabled_accepts_truthy_values(monkeypatch):
    for value in ["1", "true", "TRUE", "yes", "on"]:
        monkeypatch.setenv("ADVISORY_MOCK_CONFLICTS", value)
        assert mock_conflicts_enabled() is True


def test_mock_conflicts_enabled_rejects_falsey_values(monkeypatch):
    for value in ["", "0", "false", "no", "off", "anything_else"]:
        monkeypatch.setenv("ADVISORY_MOCK_CONFLICTS", value)
        assert mock_conflicts_enabled() is False


def test_mock_candidates_share_conflict_key_and_have_distinct_quotas():
    candidates = build_mock_conflict_candidates(
        filters={"admission_year": 2026},
        limit=100,
    )

    assert len(candidates) == 3
    keys = {
        (
            candidate.school_id,
            candidate.admission_year,
            candidate.program_id,
            candidate.admission_method,
        )
        for candidate in candidates
    }
    assert keys == {("vnu_uet", 2026, "cntt", "thpt_score")}

    quotas = {candidate.quota["value"] for candidate in candidates}
    assert quotas == {120, 150}

    for candidate in candidates:
        assert candidate.metadata["mock_conflict"] is True
        assert candidate.metadata["mock_dataset"] == "advisory_conflict_v1"
        assert candidate.evidence
        assert candidate.evidence[0].source_url.startswith("mock://")
        assert candidate.evidence[0].field_name == "quota"


def test_fetch_candidates_uses_mock_without_opening_db(monkeypatch):
    monkeypatch.setenv("ADVISORY_MOCK_CONFLICTS", "1")

    def fail_get_cursor(*args, **kwargs):
        raise AssertionError("DB cursor should not be opened in mock retrieval mode")

    monkeypatch.setattr(retrieval_service, "get_cursor", fail_get_cursor)

    candidates = retrieval_service.fetch_candidates({"admission_year": 2026})

    assert len(candidates) == 3
    assert {candidate.quota["value"] for candidate in candidates} == {120, 150}


def test_fetch_candidates_mock_respects_preferred_school_filter(monkeypatch):
    monkeypatch.setenv("ADVISORY_MOCK_CONFLICTS", "1")

    candidates = retrieval_service.fetch_candidates(
        {"admission_year": 2026, "preferred_schools": ["hust"]}
    )

    assert candidates == []


def test_fetch_candidates_mock_respects_preferred_major_filter(monkeypatch):
    monkeypatch.setenv("ADVISORY_MOCK_CONFLICTS", "1")

    candidates = retrieval_service.fetch_candidates(
        {"admission_year": 2026, "preferred_majors": ["kinh_te"]}
    )

    assert candidates == []


def test_fetch_candidates_mock_allows_matching_major_name(monkeypatch):
    monkeypatch.setenv("ADVISORY_MOCK_CONFLICTS", "1")

    candidates = retrieval_service.fetch_candidates(
        {"admission_year": 2026, "preferred_majors": ["cong_nghe_thong_tin"]}
    )

    assert len(candidates) == 3


def test_retrieval_agent_keeps_mock_conflicts_for_conflict_node(monkeypatch):
    monkeypatch.setenv("ADVISORY_MOCK_CONFLICTS", "1")
    state = AgentState(
        user_query="Tu van CNTT UET",
        student_profile=StudentProfile(
            preferred_schools=["vnu_uet"],
            preferred_majors=["cntt"],
            subject_combination="A00",
        ),
        admission_year=2026,
    )

    output = retrieval_agent(state)

    assert len(output.retrieved_programs) == 3
    assert output.conflicts == []
