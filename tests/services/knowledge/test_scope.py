from services.knowledge.scope import NATIONAL_SCHOOL, NATIONAL_DOCUMENT_TYPE


def test_national_scope_constants():
    assert NATIONAL_SCHOOL == "MOET"
    assert NATIONAL_DOCUMENT_TYPE == "national_regulation"
