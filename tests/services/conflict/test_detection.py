from domain.models import CandidateProgram, CutoffEntry, Evidence
from services.conflict.detection import detect_cutoff_conflicts, detect_quota_conflicts


def candidate(
    *,
    quota,
    source_url,
    trust=2,
    school_id="vnu_uet",
    year=2026,
    program_id="cntt",
    program_name="Cong nghe thong tin",
    method="thpt_score",
):
    return CandidateProgram(
        candidate_id=f"{school_id}:{year}:{program_id}:{method}",
        school_id=school_id,
        school_name="Dai hoc Cong nghe - DHQGHN",
        admission_year=year,
        program_id=program_id,
        program_name=program_name,
        admission_method=method,
        quota=quota,
        evidence=[
            Evidence(
                source_url=source_url,
                school_name="Dai hoc Cong nghe - DHQGHN",
                admission_year=year,
                field_name="quota",
                normalized_value=quota,
                trust_level=trust,
                confidence_score=0.9,
            )
        ],
    )


def test_detects_single_group_with_distinct_quota_values():
    conflicts = detect_quota_conflicts(
        [
            candidate(quota={"value": 120, "unit": "students"}, source_url="mock://a"),
            candidate(quota={"value": 150, "unit": "students"}, source_url="mock://b"),
        ]
    )

    assert len(conflicts) == 1
    record = conflicts[0]
    assert record.conflict_key == "vnu_uet:2026:cntt:thpt_score"
    assert record.field_name == "quota"
    assert [option.value for option in record.options] == [120, 150]


def test_no_conflict_when_quotas_are_identical():
    conflicts = detect_quota_conflicts(
        [
            candidate(quota={"value": 150, "unit": "students"}, source_url="mock://a"),
            candidate(quota={"value": 150, "unit": "students"}, source_url="mock://b"),
        ]
    )

    assert conflicts == []


def test_preserves_three_options_for_corroboration():
    conflicts = detect_quota_conflicts(
        [
            candidate(quota={"value": 120, "unit": "students"}, source_url="mock://a"),
            candidate(quota={"value": 150, "unit": "students"}, source_url="mock://b"),
            candidate(quota={"value": 150, "unit": "students"}, source_url="mock://c"),
        ]
    )

    assert len(conflicts) == 1
    assert [option.source_url for option in conflicts[0].options] == [
        "mock://a",
        "mock://b",
        "mock://c",
    ]


def test_does_not_cross_contaminate_groups():
    conflicts = detect_quota_conflicts(
        [
            candidate(quota={"value": 120}, source_url="mock://a", program_id="cntt"),
            candidate(quota={"value": 150}, source_url="mock://b", program_id="cntt"),
            candidate(quota={"value": 200}, source_url="mock://c", program_id="ktmt"),
            candidate(quota={"value": 200}, source_url="mock://d", program_id="ktmt"),
        ]
    )

    assert len(conflicts) == 1
    assert conflicts[0].program_id == "cntt"


def test_heterogeneous_quota_shapes_are_conflict_eligible():
    conflicts = detect_quota_conflicts(
        [
            candidate(quota={"value": 150}, source_url="mock://a"),
            candidate(quota={"raw": "150 chi tieu"}, source_url="mock://b"),
        ]
    )

    assert len(conflicts) == 1


def _cutoff_candidate(candidate_id="hust:2026:computer_science:thpt_score", history=()):
    return CandidateProgram(
        candidate_id=candidate_id, school_id="hust", school_name="HUST",
        admission_year=2026, program_id="computer_science",
        program_name="Khoa hoc May tinh", admission_method="thpt_score",
        cutoff_history=list(history),
    )


def _ce(year, score, source, trust=5):
    return CutoffEntry(cutoff_year=year, admission_method="thpt_score",
                       cutoff_score=score, score_scale=30.0,
                       source_url=source, trust_level=trust)


def test_detect_cutoff_conflicts_two_sources_distinct_values():
    candidate = _cutoff_candidate(history=[
        _ce(2025, 26.2, "https://truong/dc"), _ce(2025, 26.8, "https://dhqg/dc", trust=4),
    ])
    records = detect_cutoff_conflicts([candidate])

    assert len(records) == 1
    record = records[0]
    assert record.field_name == "cutoff_score"
    assert record.admission_year == 2025                  # mang CUTOFF_YEAR
    assert record.conflict_key.endswith(":cutoff")
    assert {o.value for o in record.options} == {26.2, 26.8}


def test_detect_cutoff_conflicts_dedupes_shared_history_across_rows():
    """Hai candidate row (2 phương thức) chia sẻ cùng history (attach theo school+program)
    → options KHÔNG được nhân đôi."""
    history = [_ce(2025, 26.2, "https://a"), _ce(2025, 26.8, "https://b")]
    rows = [
        _cutoff_candidate(history=history),
        _cutoff_candidate(candidate_id="hust:2026:computer_science:talent", history=history),
    ]
    records = detect_cutoff_conflicts(rows)
    assert len(records) == 1 and len(records[0].options) == 2


def test_detect_cutoff_conflicts_ignores_same_value_or_single_source():
    same = _cutoff_candidate(history=[_ce(2025, 26.2, "https://a"), _ce(2025, 26.2, "https://b")])
    single = _cutoff_candidate(history=[_ce(2025, 26.2, "https://a")])
    assert detect_cutoff_conflicts([same]) == []
    assert detect_cutoff_conflicts([single]) == []


def test_detect_cutoff_conflicts_groups_per_year():
    candidate = _cutoff_candidate(history=[
        _ce(2025, 26.2, "https://a"), _ce(2025, 26.8, "https://b"),
        _ce(2024, 25.0, "https://a"),                     # năm khác, 1 nguồn → không conflict
    ])
    records = detect_cutoff_conflicts([candidate])
    assert len(records) == 1 and records[0].admission_year == 2025
