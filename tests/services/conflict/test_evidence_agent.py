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


class _FakeRepo:
    """Captures calls; returns a preset fetched_at map (or raises)."""

    def __init__(self, mapping=None, exc=None):
        self._mapping = mapping or {}
        self._exc = exc
        self.calls = []

    def fetch_fetched_at_by_source(self, source_urls, school_id, admission_year):
        self.calls.append((list(source_urls), school_id, admission_year))
        if self._exc is not None:
            raise self._exc
        return dict(self._mapping)


def test_package_evidence_uses_candidate_evidence_for_mock_sources():
    candidates = [
        candidate("mock://uet/program-page", 120, trust=2),
        candidate("mock://vnu/proposal-pdf", 150, trust=3),
    ]
    record = detect_quota_conflicts(candidates)[0]

    class _ExplodingRepo:
        def fetch_fetched_at_by_source(self, *a, **k):
            raise AssertionError("DB should not be used for mock evidence")

    options = package_evidence(record, candidates, _evidence_repo=_ExplodingRepo())

    assert [option.source_url for option in options] == [
        "mock://uet/program-page",
        "mock://vnu/proposal-pdf",
    ]
    assert [option.trust_level for option in options] == [2, 3]


def test_package_evidence_keeps_options_when_db_enrichment_missing():
    candidates = [
        candidate("https://uet.vnu.edu.vn/a", 120),
        candidate("https://vnu.edu.vn/b.pdf", 150),
    ]
    record = detect_quota_conflicts(candidates)[0]

    options = package_evidence(record, candidates, _evidence_repo=_FakeRepo(mapping={}))

    assert len(options) == 2
    assert all(option.fetched_at is None for option in options)


def test_package_evidence_degrades_when_repo_raises():
    candidates = [
        candidate("https://uet.vnu.edu.vn/a", 120),
        candidate("https://vnu.edu.vn/b.pdf", 150),
    ]
    record = detect_quota_conflicts(candidates)[0]

    repo = _FakeRepo(exc=RuntimeError("DB down"))
    options = package_evidence(record, candidates, _evidence_repo=repo)

    assert len(options) == 2
    assert all(option.fetched_at is None for option in options)


def test_package_evidence_batches_db_lookup_into_one_query():
    candidates = [
        candidate("https://uet.vnu.edu.vn/a", 120),
        candidate("https://vnu.edu.vn/b.pdf", 150),
    ]
    record = detect_quota_conflicts(candidates)[0]

    repo = _FakeRepo(mapping={
        "https://uet.vnu.edu.vn/a": "2026-01-01",
        "https://vnu.edu.vn/b.pdf": "2026-01-02",
    })

    options = package_evidence(record, candidates, _evidence_repo=repo)

    assert len(repo.calls) == 1  # one batched lookup for the whole record
    assert {o.source_url: o.fetched_at for o in options} == {
        "https://uet.vnu.edu.vn/a": "2026-01-01",
        "https://vnu.edu.vn/b.pdf": "2026-01-02",
    }
