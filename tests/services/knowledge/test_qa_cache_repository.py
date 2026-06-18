from services.knowledge.qa_cache import QACacheRepository, scope_key_for
from services.knowledge.scope import NATIONAL_SCHOOL


def test_scope_key_for_concrete_topic():
    assert scope_key_for("HUST", "tuition") == "s:HUST|t:tuition"


def test_scope_key_for_null_topic_is_wildcard():
    assert scope_key_for("HUST", None) == "s:HUST|t:*"
    assert scope_key_for("HUST", "") == "s:HUST|t:*"


def test_scope_keys_returns_four_dependency_scopes():
    keys = QACacheRepository.scope_keys("HUST", "tuition")
    assert keys == [
        "s:HUST|t:tuition",
        "s:HUST|t:*",
        f"s:{NATIONAL_SCHOOL}|t:tuition",
        f"s:{NATIONAL_SCHOOL}|t:*",
    ]
