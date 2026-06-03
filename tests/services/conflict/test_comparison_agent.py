from services.conflict.comparison_agent import compare
from services.conflict.models import EvidenceOption


def option(value, trust=2, source="mock://a", confidence=0.9, fetched_at=None):
    return EvidenceOption(
        evidence_id=f"{source}|quota",
        source_url=source,
        trust_level=trust,
        confidence_score=confidence,
        fetched_at=fetched_at,
        value=value,
    )


def test_trust_level_can_be_decisive():
    report = compare([option(120, trust=2), option(150, trust=3, source="mock://b")])

    assert report.is_decisive is True
    assert report.ranked_options[0].value == 150
    assert report.decision_axes == ["trust_level"]


def test_corroboration_can_be_decisive():
    report = compare(
        [
            option(120, trust=2, source="mock://a"),
            option(150, trust=2, source="mock://b"),
            option(150, trust=2, source="mock://c"),
        ]
    )

    assert report.is_decisive is True
    assert report.ranked_options[0].value == 150
    assert "corroboration" in report.decision_axes


def test_all_tie_is_indecisive():
    report = compare([option(120, trust=2), option(150, trust=2, source="mock://b")])

    assert report.is_decisive is False
