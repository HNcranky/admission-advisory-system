from services.db import pool as pool_mod
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
    assert s.DB_POOL_ENABLED is True


def test_leased_connection_close_returns_connection_to_pool(monkeypatch):
    class FakePooledConn(FakeConn):
        pass

    class FakePool:
        instances = []

        def __init__(self, *args, **kwargs):
            self.conn = FakePooledConn()
            self.putconn_calls = []
            FakePool.instances.append(self)

        def getconn(self):
            return self.conn

        def putconn(self, conn):
            self.putconn_calls.append(conn)

        def closeall(self):
            pass

    close_all()
    monkeypatch.setattr(pool_mod, "ThreadedConnectionPool", FakePool)

    conn = pool_mod.lease({
        "host": "localhost",
        "port": 5432,
        "database": "admission_test",
        "user": "postgres",
        "password": "postgres",
    })
    conn.close()

    fake_pool = FakePool.instances[0]
    assert fake_pool.putconn_calls == [fake_pool.conn]
    assert fake_pool.conn.closed is False
    close_all()
