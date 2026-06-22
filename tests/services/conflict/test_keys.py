from types import SimpleNamespace

from services.conflict.keys import (
    quota_key_tuple,
    quota_key_text,
    quota_key_text_from_tuple,
    cutoff_key_text,
)


def _cand(**kw):
    base = dict(
        school_id="HUST",
        admission_year=2026,
        program_id="IT1",
        program_name="CNTT",
        admission_method="thpt",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_quota_key_text_basic():
    assert quota_key_text(_cand()) == "HUST:2026:IT1:thpt"


def test_quota_key_falls_back_to_program_name_when_no_id():
    assert quota_key_text(_cand(program_id=None)) == "HUST:2026:CNTT:thpt"


def test_quota_key_unknown_method_when_none():
    assert quota_key_text(_cand(admission_method=None)) == "HUST:2026:IT1:unknown_method"


def test_quota_tuple_and_text_consistent():
    c = _cand()
    assert quota_key_text_from_tuple(quota_key_tuple(c)) == quota_key_text(c)


def test_cutoff_key_text():
    assert cutoff_key_text("HUST", 2024, "IT1", "thpt") == "HUST:2024:IT1:thpt:cutoff"
