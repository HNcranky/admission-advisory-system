from services.knowledge.retrieval_query import build_retrieval_query


def test_standalone_question_with_topic_noun_returned_verbatim():
    q = "học phí của HUST là bao nhiêu"
    assert build_retrieval_query(q, "ngành CNTT thế nào") == q


def test_continuation_cue_prepends_prev_user():
    q = "còn ngành CNTT thì sao"
    prev = "học phí HUST bao nhiêu"
    assert build_retrieval_query(q, prev) == f"{prev}\n{q}"


def test_short_question_without_noun_or_cue_prepends():
    q = "cái đó thế nào"  # short, no topic noun, no leading cue → elliptical
    prev = "HUST tuyển sinh ra sao"
    assert build_retrieval_query(q, prev) == f"{prev}\n{q}"


def test_empty_prev_user_returns_question_verbatim():
    q = "còn thì sao"
    assert build_retrieval_query(q, "") == q
    assert build_retrieval_query(q, "   ") == q


def test_long_question_not_treated_as_elliptical():
    # >8 words and contains a topic noun → self-contained, returned verbatim
    q = "cho mình hỏi mức học phí của trường đại học bách khoa năm nay là bao nhiêu"
    assert build_retrieval_query(q, "câu trước đó") == q


def test_none_inputs_do_not_crash():
    assert build_retrieval_query(None, None) == ""
