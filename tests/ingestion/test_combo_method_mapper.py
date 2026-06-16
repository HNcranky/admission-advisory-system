import ingestion.normalization.combo_method_mapper as cmm

_FAKE_RULES = {
    "_shared": {
        "rules": [
            {"combo_pattern": r"^K0\d$", "method_code": "competency_test", "description": "DGTD"},
        ]
    }
}


def test_infer_methods_first_rule_match(monkeypatch):
    monkeypatch.setattr(cmm, "_load_rules", lambda: _FAKE_RULES)
    assert cmm.infer_methods_from_combos(["K01"], school_id="hust") == ["competency_test"]


def test_infer_methods_no_match_empty(monkeypatch):
    monkeypatch.setattr(cmm, "_load_rules", lambda: _FAKE_RULES)
    assert cmm.infer_methods_from_combos(["A00"], school_id="hust") == []


def test_infer_methods_none_empty(monkeypatch):
    monkeypatch.setattr(cmm, "_load_rules", lambda: _FAKE_RULES)
    assert cmm.infer_methods_from_combos(None, school_id="hust") == []
