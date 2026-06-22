import ingestion.normalization.method_mapper as mm

# map_method chỉ dùng _load_dict(school_id) và so khớp substring (raw==candidate
# hoặc candidate ⊂ raw) trên text GIỮ NGUYÊN dấu ⇒ alias phải có dấu mới khớp.
_FAKE = {
    "_shared": {
        "thpt_score": {
            "canonical_name": "Xét điểm thi TN THPT",
            "aliases": ["xét điểm thi", "kết quả thi"],
        }
    }
}


def test_map_method_alias_substring_hits_code(monkeypatch):
    monkeypatch.setattr(mm, "_load_all", lambda: _FAKE)
    monkeypatch.setattr(mm, "_load_dict", lambda school_id="": _FAKE["_shared"])
    # alias "xét điểm thi" là substring của raw ⇒ trả code.
    assert mm.map_method("Xét điểm thi tốt nghiệp", school_id="hust") == "thpt_score"


def test_map_method_unknown_returns_raw(monkeypatch):
    # QUIRK pinned: không khớp ⇒ trả lại raw text (KHÔNG None).
    monkeypatch.setattr(mm, "_load_all", lambda: _FAKE)
    monkeypatch.setattr(mm, "_load_dict", lambda school_id="": _FAKE["_shared"])
    assert mm.map_method("phương thức lạ hoắc", school_id="hust") == "phương thức lạ hoắc"


def test_map_method_none_returns_none(monkeypatch):
    monkeypatch.setattr(mm, "_load_all", lambda: _FAKE)
    monkeypatch.setattr(mm, "_load_dict", lambda school_id="": _FAKE["_shared"])
    assert mm.map_method(None) is None
