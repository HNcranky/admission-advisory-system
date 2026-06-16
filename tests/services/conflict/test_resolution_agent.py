from services.conflict.comparison_agent import compare
from services.conflict.models import ConflictRecord, EvidenceOption
from services.conflict.resolution_agent import resolve


def option(value, trust=2, source="mock://a"):
    return EvidenceOption(
        evidence_id=f"{source}|quota",
        source_url=source,
        trust_level=trust,
        confidence_score=0.9,
        value=value,
    )


def record(options):
    return ConflictRecord(
        conflict_key="vnu_uet:2026:cntt:thpt_score",
        field_name="quota",
        school_id="vnu_uet",
        school_name="Dai hoc Cong nghe - DHQGHN",
        admission_year=2026,
        program_id="cntt",
        program_name="Cong nghe thong tin",
        admission_method="thpt_score",
        options=options,
    )


def test_decisive_report_resolves():
    options = [option(120, trust=2), option(150, trust=3, source="mock://b")]

    outcome = resolve(record(options), compare(options))

    assert outcome.status == "resolved"
    assert outcome.resolved_value == 150
    assert outcome.chosen_evidence.source_url == "mock://b"


def test_all_axes_tie_resolves_unresolved():
    # Same trust + confidence, no fetched_at on either, distinct values ->
    # corroboration ties too -> compare() is NOT decisive.
    options = [option(120, trust=2), option(150, trust=2, source="mock://b")]
    report = compare(options)
    assert report.is_decisive is False

    outcome = resolve(record(options), report)

    assert outcome.status == "unresolved"
    assert outcome.resolved_value is None
    assert outcome.uncertainty_reason
