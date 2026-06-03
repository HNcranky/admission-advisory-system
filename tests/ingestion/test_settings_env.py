from ingestion.config import settings


def test_load_env_file_sets_missing_values(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        'GEMINI_API_KEY="from-file"\n'
        "# ignored comment\n"
        "GEMINI_EXTRACTION_MODEL=gemini-test\n",
        encoding="utf-8",
    )

    settings._load_env_file(env_file)

    assert settings.os.environ["GEMINI_API_KEY"] == "from-file"
    assert settings.os.environ["GEMINI_EXTRACTION_MODEL"] == "gemini-test"


def test_load_env_file_keeps_existing_environment_values(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "from-shell")
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=from-file\n", encoding="utf-8")

    settings._load_env_file(env_file)

    assert settings.os.environ["GEMINI_API_KEY"] == "from-shell"


def test_gemini_key_cooldown_seconds_default_is_positive_float():
    from ingestion.config import settings

    assert isinstance(settings.GEMINI_KEY_COOLDOWN_SECONDS, float)
    assert settings.GEMINI_KEY_COOLDOWN_SECONDS > 0
