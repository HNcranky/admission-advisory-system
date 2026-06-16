import pytest

from services.db.pool import release, close_all


class FakeConn:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_release_closes_unpooled_connection():
    c = FakeConn()
    release(c)  # no _advisory_pool_key tag → falls back to close()
    assert c.closed is True


def test_pool_enabled_by_default(monkeypatch):
    monkeypatch.delenv("DB_POOL_ENABLED", raising=False)
    import importlib
    import ingestion.config.settings as s
    importlib.reload(s)
    # After PR7 this default flips to True; until then it stays False.
    # This test is updated in PR7 to assert True.
    assert s.DB_POOL_ENABLED is False
