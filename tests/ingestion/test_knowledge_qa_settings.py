from ingestion.config import settings


def test_knowledge_qa_top_k_default_is_5():
    assert settings.KNOWLEDGE_QA_TOP_K == 5


def test_knowledge_qa_min_score_default_is_half():
    assert settings.KNOWLEDGE_QA_MIN_SCORE == 0.5


def test_knowledge_qa_top_k_env_overridable(monkeypatch):
    import importlib

    monkeypatch.setenv("KNOWLEDGE_QA_TOP_K", "8")
    reloaded = importlib.reload(settings)
    try:
        assert reloaded.KNOWLEDGE_QA_TOP_K == 8
    finally:
        monkeypatch.delenv("KNOWLEDGE_QA_TOP_K", raising=False)
        importlib.reload(settings)  # restore defaults for other tests
