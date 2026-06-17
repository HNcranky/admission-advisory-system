import observability.langfuse_client as lc


def _reset():
    lc.reset_langfuse_client()


def test_disabled_returns_none(monkeypatch):
    monkeypatch.setenv("ADVISORY_LANGFUSE_ENABLED", "false")
    _reset()
    assert lc.get_langfuse() is None


def test_enabled_but_missing_keys_returns_none_and_warns(monkeypatch, caplog):
    import logging
    monkeypatch.setenv("ADVISORY_LANGFUSE_ENABLED", "true")
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    _reset()
    with caplog.at_level(logging.WARNING, logger="observability.langfuse_client"):
        assert lc.get_langfuse() is None
    assert any("LANGFUSE_PUBLIC_KEY" in r.message for r in caplog.records)


def test_enabled_with_keys_builds_client_once(monkeypatch):
    monkeypatch.setenv("ADVISORY_LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setenv("LANGFUSE_HOST", "http://localhost:3000")
    _reset()

    built = []

    class _FakeLangfuse:
        def __init__(self, **kwargs):
            built.append(kwargs)

    import langfuse
    monkeypatch.setattr(langfuse, "Langfuse", _FakeLangfuse)

    first = lc.get_langfuse()
    second = lc.get_langfuse()
    assert first is second is not None
    assert len(built) == 1
    assert built[0]["public_key"] == "pk"
    assert built[0]["secret_key"] == "sk"
    assert built[0]["host"] == "http://localhost:3000"


def test_flush_is_noop_when_disabled(monkeypatch):
    monkeypatch.setenv("ADVISORY_LANGFUSE_ENABLED", "false")
    _reset()
    lc.flush_langfuse()  # must not raise
