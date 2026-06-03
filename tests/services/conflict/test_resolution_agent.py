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


def test_decisive_report_resolves_without_gateway():
    options = [option(120, trust=2), option(150, trust=3, source="mock://b")]

    def gateway_should_not_run(*args, **kwargs):
        raise AssertionError("Gateway should not run for decisive comparison")

    outcome = resolve(record(options), compare(options), gateway=gateway_should_not_run)

    assert outcome.status == "resolved"
    assert outcome.resolved_value == 150
    assert outcome.chosen_evidence.source_url == "mock://b"
    assert outcome.used_llm_tiebreaker is False


def test_indecisive_medium_gateway_result_stays_unresolved():
    options = [option(120, trust=2), option(150, trust=2, source="mock://b")]

    def gateway(*args, **kwargs):
        return {
            "chosen_source_url": "mock://b",
            "confidence": "medium",
            "rationale": "Tie remains uncertain.",
        }

    outcome = resolve(record(options), compare(options), gateway=gateway)

    assert outcome.status == "unresolved"
    assert outcome.resolved_value is None
    assert outcome.uncertainty_reason
