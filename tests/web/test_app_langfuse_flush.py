import observability.langfuse_client as lc
from web.app import build_app


def test_app_flushes_langfuse_on_shutdown(monkeypatch):
    called = []
    monkeypatch.setattr(lc, "flush_langfuse", lambda: called.append(True))

    app = build_app()
    for handler in app.router.on_shutdown:
        handler()

    assert called == [True]
