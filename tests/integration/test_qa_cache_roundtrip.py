import pytest

from services.knowledge.models import Citation, KnowledgeQAResult
from services.knowledge.qa_cache import QACacheRepository

pytestmark = pytest.mark.integration

_SCHOOL, _TOPIC = "ITEST", "tuition"


def _result():
    return KnowledgeQAResult(
        has_data=True,
        answer="Học phí ITEST 35 triệu/năm.",
        citations=[Citation(source_url="http://itest/fee", chunk_text="đoạn học phí")],
        confidence=0.91,
    )


def _store_fresh(repo, embedding):
    dep = repo.current_versions(repo.scope_keys(_SCHOOL, _TOPIC))
    repo.store(_SCHOOL, _TOPIC, "học phí ITEST?", embedding, _result(), dep, ttl_days=30)


def test_store_then_lookup_round_trip(db_available, qa_cache_clean):
    repo = QACacheRepository()
    vec = [0.1] * 768
    _store_fresh(repo, vec)

    hit = repo.lookup(vec, _SCHOOL, _TOPIC, threshold=0.95)
    assert hit is not None
    assert hit.answer == "Học phí ITEST 35 triệu/năm."
    assert hit.citations[0].source_url == "http://itest/fee"


def test_lookup_misses_on_distant_embedding(db_available, qa_cache_clean):
    repo = QACacheRepository()
    stored_vec = [1.0] + [0.0] * 767
    _store_fresh(repo, stored_vec)

    far_vec = [0.0, 1.0] + [0.0] * 766   # orthogonal → cosine 0
    assert repo.lookup(far_vec, _SCHOOL, _TOPIC, threshold=0.95) is None


def test_bumping_a_dependency_scope_makes_row_stale(db_available, qa_cache_clean):
    repo = QACacheRepository()
    vec = [0.1] * 768
    _store_fresh(repo, vec)
    assert repo.lookup(vec, _SCHOOL, _TOPIC, threshold=0.95) is not None

    # A new/edited doc in the school's wildcard scope bumps that version.
    repo.bump_version("s:ITEST|t:*")
    assert repo.lookup(vec, _SCHOOL, _TOPIC, threshold=0.95) is None
