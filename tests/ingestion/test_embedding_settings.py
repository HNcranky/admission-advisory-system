from ingestion.config import settings


def test_embedding_dim_is_768():
    assert settings.EMBEDDING_DIM == 768


def test_embedding_model_defaults_to_gemini_embedding_001():
    assert settings.GEMINI_EMBEDDING_MODEL == "gemini-embedding-001"


def test_embedding_model_is_env_overridable(monkeypatch):
    # Reload the module under a patched env var to prove the override path works.
    import importlib

    monkeypatch.setenv("GEMINI_EMBEDDING_MODEL", "text-embedding-004")
    reloaded = importlib.reload(settings)
    try:
        assert reloaded.GEMINI_EMBEDDING_MODEL == "text-embedding-004"
    finally:
        monkeypatch.delenv("GEMINI_EMBEDDING_MODEL", raising=False)
        importlib.reload(settings)  # restore defaults for other tests
