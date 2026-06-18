from ingestion.config import settings


def test_cache_settings_have_spec_defaults():
    assert settings.KNOWLEDGE_QA_CACHE_ENABLED is True
    assert settings.KNOWLEDGE_QA_CACHE_THRESHOLD == 0.95
    assert settings.KNOWLEDGE_QA_CACHE_TTL_DAYS == 30
