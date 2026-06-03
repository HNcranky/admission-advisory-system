from datetime import datetime

from services.conflict.models import (
    ComparisonReport,
    ConflictRecord,
    EvidenceOption,
    ResolutionOutcome,
)


def _option(value=100, trust=2, url="mock://source-a"):
    return EvidenceOption(
        evidence_id=f"{url}|quota",
        source_url=url,
        trust_level=trust,
        fetched_at=datetime(2026, 1, 1),
        confidence_score=0.9,
        value=value,
    )


def test_evidence_option_allows_missing_optional_provenance():
    option = EvidenceOption(evidence_id="x|quota", source_url="mock://x", value=120)

    assert option.trust_level is None
    assert option.fetched_at is None
    assert option.confidence_score is None


def test_conflict_record_carries_conflict_key_and_options():
    record = ConflictRecord(
        conflict_key="vnu_uet:2026:cntt:thpt_score",
        field_name="quota",
        school_id="vnu_uet",
        school_name="Dai hoc Cong nghe - DHQGHN",
        admission_year=2026,
        program_id="cntt",
        program_name="Cong nghe thong tin",
        admission_method="thpt_score",
        options=[_option(120), _option(150)],
    )

    assert record.field_name == "quota"
    assert record.admission_year == 2026
    assert [option.value for option in record.options] == [120, 150]


def test_comparison_report_and_resolution_outcome_shape():
    winning = _option(150, trust=3, url="mock://winner")
    losing = _option(120, trust=2, url="mock://loser")

    report = ComparisonReport(
        ranked_options=[winning, losing],
        is_decisive=True,
        decision_axes=["trust_level"],
    )
    outcome = ResolutionOutcome(
        conflict_key="vnu_uet:2026:cntt:thpt_score",
        field_name="quota",
        school_id="vnu_uet",
        school_name="Dai hoc Cong nghe - DHQGHN",
        program_name="Cong nghe thong tin",
        status="resolved",
        resolved_value=150,
        chosen_evidence=winning,
        rejected_evidence=[losing],
        rationale="Trusted source has higher trust level.",
        decision_axes=report.decision_axes,
    )

    assert outcome.status == "resolved"
    assert outcome.chosen_evidence == winning
    assert outcome.rejected_evidence == [losing]
