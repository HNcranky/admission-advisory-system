from collections import Counter
from typing import List

from services.conflict.models import ComparisonReport, EvidenceOption


def _score(option: EvidenceOption, corroboration: Counter) -> tuple:
    return (
        option.trust_level if option.trust_level is not None else -1,
        corroboration[str(option.value)],
        option.fetched_at is not None,
        option.fetched_at,
        option.confidence_score if option.confidence_score is not None else -1.0,
    )


def compare(options: List[EvidenceOption]) -> ComparisonReport:
    if not options:
        return ComparisonReport(ranked_options=[], is_decisive=False, decision_axes=[])

    corroboration = Counter(str(option.value) for option in options)
    ranked = sorted(options, key=lambda option: _score(option, corroboration), reverse=True)
    if len(ranked) == 1:
        return ComparisonReport(ranked_options=ranked, is_decisive=True, decision_axes=["single_option"])

    first = ranked[0]
    challenger = next((option for option in ranked[1:] if option.value != first.value), ranked[1])
    first_score = _score(first, corroboration)
    second_score = _score(challenger, corroboration)
    if first_score == second_score:
        return ComparisonReport(ranked_options=ranked, is_decisive=False, decision_axes=[])

    axes = []
    if first_score[0] != second_score[0]:
        axes.append("trust_level")
    elif first_score[1] != second_score[1]:
        axes.append("corroboration")
    elif first_score[3] != second_score[3]:
        axes.append("recency")
    elif first_score[4] != second_score[4]:
        axes.append("confidence_score")

    return ComparisonReport(ranked_options=ranked, is_decisive=True, decision_axes=axes)
