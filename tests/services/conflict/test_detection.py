from agents.models import CandidateProgram, Evidence
from services.conflict.detection import detect_quota_conflicts


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
