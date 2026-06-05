from agents.models import CutoffEntry
from services.cutoff.assessment import assess_cutoff, classify_margin


def _e(year, score, source="https://ts.hust.edu.vn/dc", trust=5, method="thpt_score", scale=30.0):
    return CutoffEntry(cutoff_year=year, admission_method=method, cutoff_score=score,
                       score_scale=scale, source_url=source, trust_level=trust)


# ─── classify_margin ──────────────────────────────────────────────────────────

def test_classify_margin_bands():
    assert classify_margin(26.0, 26.5) == "below"        # margin < 0
    assert classify_margin(26.20, 26.20) == "borderline" # margin = 0
    assert classify_margin(26.25, 26.20) == "borderline" # EC-14: +0.05
    assert classify_margin(26.45, 26.20) == "above"      # +0.25 = ngưỡng trên của borderline
    assert classify_margin(28.0, 26.5) == "above"


# ─── Gate trả None ────────────────────────────────────────────────────────────

def test_gate_returns_none_without_score_or_method_or_history():
    history = [_e(2025, 26.2)]
    assert assess_cutoff(None, "thpt_score", history) is None
    assert assess_cutoff(27.0, None, history) is None
    assert assess_cutoff(27.0, "competency_test", history) is None   # ngoài thang 30
    assert assess_cutoff(27.0, "thpt_score", []) is None
    # entry khác method / khác thang bị lọc hết → None (KHÔNG quy đổi thang)
    assert assess_cutoff(27.0, "thpt_score", [_e(2025, 80, method="competency_test", scale=150.0)]) is None
    assert assess_cutoff(27.0, "thpt_score", [_e(2025, 80, scale=150.0)]) is None


# ─── EC-14: sát ngưỡng ───────────────────────────────────────────────────────

def test_ec14_borderline_margin():
    a = assess_cutoff(26.25, "thpt_score", [_e(2025, 26.20)])
    assert a.score_fit == "borderline"
    assert a.reference_year == 2025
    assert a.margin == 0.05
    assert a.conflicted is False and a.decision_changing is False and a.volatile is False


# ─── EC-15: biến động lịch sử ────────────────────────────────────────────────

def test_ec15_volatile_history_overrides_to_uncertain():
    history = [_e(2023, 24.8), _e(2024, 26.7), _e(2025, 25.9)]
    a = assess_cutoff(26.4, "thpt_score", history)
    assert a.score_fit == "uncertain"                    # override dù margin 2025 = +0.5 (above)
    assert a.volatile is True
    assert a.volatility_min == 24.8 and a.volatility_max == 26.7
    assert a.years_used == [2023, 2024, 2025]
    assert a.reference_year == 2025 and a.margin == 0.5


def test_two_years_never_volatile():
    a = assess_cutoff(26.4, "thpt_score", [_e(2024, 24.0), _e(2025, 25.9)])
    assert a.volatile is False and a.score_fit == "above"


def test_stable_three_years_not_volatile():
    a = assess_cutoff(27.0, "thpt_score", [_e(2023, 26.0), _e(2024, 26.4), _e(2025, 26.5)])
    assert a.volatile is False and a.score_fit == "above"


# ─── EC-16: hai nguồn lệch nhau ──────────────────────────────────────────────

def test_ec16_decision_changing_conflict_takes_conservative_label():
    history = [
        _e(2025, 26.2, source="https://truong.example/dc", trust=4),
        _e(2025, 26.8, source="https://dhqg.example/dc", trust=5),
    ]
    a = assess_cutoff(26.5, "thpt_score", history)
    # 26.5−26.2=+0.3→above; 26.5−26.8=−0.3→below ⇒ nhãn bảo thủ = below
    assert a.conflicted is True and a.decision_changing is True
    assert a.score_fit == "below"
    assert {v["value"] for v in a.latest_values} == {26.2, 26.8}
    # margin tính theo nguồn trust cao nhất (26.8)
    assert a.margin == -0.3


def test_conflict_same_label_is_not_decision_changing():
    history = [_e(2025, 25.0, trust=5), _e(2025, 25.2, source="https://b", trust=4)]
    a = assess_cutoff(27.0, "thpt_score", history)
    assert a.conflicted is True and a.decision_changing is False
    assert a.score_fit == "above"


def test_trust_tiebreak_prefers_higher_cutoff_when_equal_trust():
    history = [_e(2025, 26.0, trust=5), _e(2025, 26.4, source="https://b", trust=5)]
    a = assess_cutoff(28.0, "thpt_score", history)
    assert a.margin == 1.6                               # so với 26.4 (giá trị cao hơn = bảo thủ hơn)


def test_scale_none_treated_as_thang_30():
    a = assess_cutoff(27.0, "thpt_score", [_e(2025, 26.0, scale=None)])
    assert a is not None and a.score_fit == "above"
