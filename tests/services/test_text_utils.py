from services.text_utils import vietnamese_fold


def test_fold_maps_d_stroke():
    assert vietnamese_fold("Đại học Đà Nẵng") == "dai hoc da nang"


def test_fold_strips_accents_and_lowercases():
    assert vietnamese_fold("Xét Tuyển") == "xet tuyen"


def test_fold_collapses_whitespace():
    assert vietnamese_fold("  xet   tuyen \n thang ") == "xet tuyen thang"
