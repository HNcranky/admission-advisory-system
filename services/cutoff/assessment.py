"""Đối chiếu điểm hồ sơ với điểm chuẩn lịch sử (EC-14/15/16/18) — pure, không I/O.

Hằng số là tham số chỉnh được (docs/edge-case.md không quy định số cụ thể);
giá trị khởi điểm được neo theo ví dụ trong doc:
- BORDERLINE_MARGIN=0.25: EC-14 (+0.05 so với cutoff) phải ra "borderline".
- VOLATILITY_RANGE=1.0:   EC-15 (range 24.8–26.7 = 1.9) phải ra "uncertain".
- SAFE_MARGIN=1.0:        chỉ margin >= 1.0 mới nhận bonus tối đa ở reasoning.
- MIN_YEARS_VOLATILITY=3: dưới 3 năm dữ liệu thì không kết luận biến động.

Tuyệt đối KHÔNG quy đổi giữa các thang điểm: entry khác method/khác thang 30
bị lọc ở gate, không bao giờ được so trực tiếp.
"""
from typing import List, Optional

from agents.models import CutoffAssessment, CutoffEntry
from services.profile.admission_methods import THANG_30_METHODS

BORDERLINE_MARGIN = 0.25
SAFE_MARGIN = 1.0
VOLATILITY_RANGE = 1.0
MIN_YEARS_VOLATILITY = 3

_FIT_ORDER = {"below": 0, "borderline": 1, "above": 2}  # nhỏ hơn = bảo thủ hơn


def classify_margin(total_score: float, cutoff_score: float) -> str:
    """Nhãn per-value: below / borderline / above (EC-14)."""
    margin = total_score - cutoff_score
    if margin < 0:
        return "below"
    if margin < BORDERLINE_MARGIN:
        return "borderline"
    return "above"


def _usable(admission_method: str, history: List[CutoffEntry]) -> List[CutoffEntry]:
    return [
        e for e in history
        if e.admission_method == admission_method
        and (e.score_scale is None or e.score_scale == 30)
    ]


def _best_of(entries: List[CutoffEntry]) -> CutoffEntry:
    """Nguồn trust cao nhất; hoà trust → giá trị cao hơn (bảo thủ: margin nhỏ hơn)."""
    return max(
        entries,
        key=lambda e: (
            e.trust_level if e.trust_level is not None else -1,
            e.cutoff_score,
        ),
    )


def assess_cutoff(
    total_score: Optional[float],
    admission_method: Optional[str],
    cutoff_history: List[CutoffEntry],
) -> Optional[CutoffAssessment]:
    """None khi không đủ điều kiện so sánh → caller giữ nguyên hành vi cũ."""
    if total_score is None or admission_method not in THANG_30_METHODS:
        return None
    entries = _usable(admission_method, cutoff_history or [])
    if not entries:
        return None

    years = sorted({e.cutoff_year for e in entries})
    reference_year = years[-1]
    latest = [e for e in entries if e.cutoff_year == reference_year]

    distinct_values = sorted({e.cutoff_score for e in latest})
    fits = {classify_margin(total_score, value) for value in distinct_values}
    conflicted = len(distinct_values) > 1
    decision_changing = len(fits) > 1
    score_fit = min(fits, key=lambda f: _FIT_ORDER[f])  # nhãn bảo thủ nhất (EC-16)

    best = _best_of(latest)
    margin = round(total_score - best.cutoff_score, 2)

    volatile = False
    volatility_min = volatility_max = None
    if len(years) >= MIN_YEARS_VOLATILITY:
        per_year = [
            _best_of([e for e in entries if e.cutoff_year == year]).cutoff_score
            for year in years
        ]
        volatility_min, volatility_max = min(per_year), max(per_year)
        if volatility_max - volatility_min >= VOLATILITY_RANGE:
            volatile = True
            score_fit = "uncertain"                      # override (EC-15)

    return CutoffAssessment(
        score_fit=score_fit,
        reference_year=reference_year,
        margin=margin,
        latest_values=[
            {"value": e.cutoff_score, "source_url": e.source_url, "trust_level": e.trust_level}
            for e in sorted(latest, key=lambda e: e.cutoff_score)
        ],
        conflicted=conflicted,
        decision_changing=decision_changing,
        volatile=volatile,
        volatility_min=volatility_min,
        volatility_max=volatility_max,
        years_used=years,
    )
