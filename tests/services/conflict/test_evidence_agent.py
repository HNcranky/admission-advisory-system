from agents.models import CandidateProgram, Evidence
from services.conflict.detection import detect_quota_conflicts
from services.conflict.evidence_agent import package_evidence


def candidate(source_url, quota, trust=2):
    return CandidateProgram(
        candidate_id="vnu_uet:2026:cntt:thpt_score",
        school_id="vnu_uet",
        school_name="Dai hoc Cong nghe - DHQGHN",
        admission_year=2026,
        program_id="cntt",
        program_name="Cong nghe thong tin",
        admission_method="thpt_score",
        quota={"value": quota, "unit": "students"},
        metadata={"mock_conflict": source_url.startswith("mock://")},
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


def test_package_evidence_uses_candidate_evidence_for_mock_sources(monkeypatch):
    candidates = [
        candidate("mock://uet/program-page", 120, trust=2),
        candidate("mock://vnu/proposal-pdf", 150, trust=3),
    ]
    record = detect_quota_conflicts(candidates)[0]

    def fail_cursor(*args, **kwargs):
        raise AssertionError("DB should not be used for mock evidence")

    monkeypatch.setattr("services.conflict.evidence_agent.get_cursor", fail_cursor)

    options = package_evidence(record, candidates)

    assert [option.source_url for option in options] == [
        "mock://uet/program-page",
        "mock://vnu/proposal-pdf",
    ]
    assert [option.trust_level for option in options] == [2, 3]


def test_package_evidence_keeps_options_when_db_enrichment_missing(monkeypatch):
    candidates = [
        candidate("https://uet.vnu.edu.vn/a", 120),
        candidate("https://vnu.edu.vn/b.pdf", 150),
    ]
    record = detect_quota_conflicts(candidates)[0]

    class Cursor:
        def execute(self, *args, **kwargs):
            return None

        def fetchone(self):
            return None

    class CursorContext:
        def __enter__(self):
            return Cursor()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("services.conflict.evidence_agent.get_cursor", lambda commit=False: CursorContext())

    options = package_evidence(record, candidates)

    assert len(options) == 2
    assert all(option.fetched_at is None for option in options)
