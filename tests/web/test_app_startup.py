import anyio.to_thread
from fastapi.testclient import TestClient

from web.app import build_app


def test_threadpool_limiter_configured(monkeypatch):
    captured = {}

    class FakeLimiter:
        def __setattr__(self, name, value):
            if name == "total_tokens":
                captured[name] = value
            object.__setattr__(self, name, value)

    fake = FakeLimiter()
    monkeypatch.setattr(anyio.to_thread, "current_default_thread_limiter", lambda: fake)
    monkeypatch.setenv("WEB_THREADPOOL_SIZE", "12")

    app = build_app()
    with TestClient(app):
        pass

    assert captured.get("total_tokens") == 12
