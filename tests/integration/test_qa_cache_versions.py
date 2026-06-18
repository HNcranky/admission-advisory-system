import pytest

from services.knowledge.qa_cache import QACacheRepository

pytestmark = pytest.mark.integration


def test_bump_version_creates_then_increments(db_available, qa_cache_clean):
    repo = QACacheRepository()
    key = "s:ITEST|t:tuition"

    # absent → version 0
    assert repo.current_versions([key]) == {key: 0}

    repo.bump_version(key)
    assert repo.current_versions([key]) == {key: 1}

    repo.bump_version(key)
    assert repo.current_versions([key]) == {key: 2}


def test_current_versions_reports_zero_for_unknown_scopes(db_available, qa_cache_clean):
    repo = QACacheRepository()
    repo.bump_version("s:ITEST|t:tuition")

    versions = repo.current_versions(QACacheRepository.scope_keys("ITEST", "tuition"))
    assert versions["s:ITEST|t:tuition"] == 1
    assert versions["s:ITEST|t:*"] == 0
    assert versions["s:MOET|t:tuition"] == 0
    assert versions["s:MOET|t:*"] == 0
