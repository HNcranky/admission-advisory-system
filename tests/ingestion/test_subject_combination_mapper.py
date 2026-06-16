import ingestion.normalization.subject_combination_mapper as scm

_FAKE = {
    "A00": {"subjects": ["Toán", "Lý", "Hoá"], "description": "Toán, Lý, Hoá"},
    "D01": {"subjects": ["Toán", "Văn", "Anh"], "description": "Toán, Văn, Anh"},
}


def test_map_combinations_by_code(monkeypatch):
    monkeypatch.setattr(scm, "_load_dict", lambda: _FAKE)
    result = scm.map_combinations(["A00", "D01"])
    assert [c.code for c in result] == ["A00", "D01"]
    assert result[0].subjects == ["Toán", "Lý", "Hoá"]


def test_map_combinations_none_or_empty(monkeypatch):
    monkeypatch.setattr(scm, "_load_dict", lambda: _FAKE)
    assert scm.map_combinations(None) == []
    assert scm.map_combinations([]) == []
