from services.knowledge.models import KnowledgeQAResult


def test_from_cache_defaults_false():
    assert KnowledgeQAResult(has_data=True, answer="x").from_cache is False


def test_from_cache_can_be_set():
    assert KnowledgeQAResult(has_data=True, answer="x", from_cache=True).from_cache is True
