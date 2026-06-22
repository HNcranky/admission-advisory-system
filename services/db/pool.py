"""Process-level connection pool registry keyed by DSN tuple.

When DB_POOL_ENABLED=true, each connection factory (services/chat/db.py,
services/knowledge/db.py, ingestion/storage/db_connection.py) calls lease()
instead of psycopg2.connect(). The cursor() context manager in services/db/__init__.py
calls release() in its finally block so pooled connections are returned rather
than closed. When DB_POOL_ENABLED=false, release() falls back to conn.close()
and behaviour is byte-for-byte identical to before."""

import threading

from psycopg2.pool import ThreadedConnectionPool

from ingestion.config.settings import DB_POOL_MIN, DB_POOL_MAX

_POOLS: dict[tuple, ThreadedConnectionPool] = {}
_POOL_LOCK = threading.Lock()

# Maps id(conn) -> pool_key so we can return pooled connections without needing
# arbitrary attributes on psycopg2 C extension objects (which don't have __dict__).
_CONN_KEYS: dict[int, tuple] = {}
_CONN_KEYS_LOCK = threading.Lock()


class PooledConnection:
    """Proxy that makes conn.close() return the raw connection to its pool."""

    def __init__(self, raw_conn):
        self._raw_conn = raw_conn
        self._released = False

    def __getattr__(self, name):
        return getattr(self._raw_conn, name)

    def close(self) -> None:
        release(self)

    @property
    def raw_connection(self):
        return self._raw_conn

    @property
    def released(self) -> bool:
        return self._released

    def mark_released(self) -> None:
        self._released = True


def _dsn_key(dsn: dict) -> tuple:
    return (dsn["host"], dsn["port"], dsn["database"], dsn["user"])


def lease(dsn: dict):
    """Return a connection from the pool for this DSN, creating the pool if needed."""
    k = _dsn_key(dsn)
    with _POOL_LOCK:
        pool = _POOLS.get(k)
        if pool is None:
            pool = ThreadedConnectionPool(
                DB_POOL_MIN, DB_POOL_MAX,
                host=dsn["host"], port=dsn["port"], dbname=dsn["database"],
                user=dsn["user"], password=dsn["password"],
            )
            _POOLS[k] = pool
    raw_conn = pool.getconn()
    conn = PooledConnection(raw_conn)
    with _CONN_KEYS_LOCK:
        _CONN_KEYS[id(conn)] = k
    return conn


def release(conn) -> None:
    """Return conn to its pool if it was leased, or close it if not."""
    conn_id = id(conn)
    if isinstance(conn, PooledConnection) and conn.released:
        return

    with _CONN_KEYS_LOCK:
        key = _CONN_KEYS.pop(conn_id, None)
    if key is None:
        if isinstance(conn, PooledConnection):
            conn.mark_released()
            conn.raw_connection.close()
        else:
            conn.close()
        return
    with _POOL_LOCK:
        pool = _POOLS.get(key)
    if pool is None:
        conn.mark_released()
        conn.raw_connection.close()
    else:
        conn.mark_released()
        pool.putconn(conn.raw_connection)


def close_all() -> None:
    """Close every pool (useful in tests and graceful shutdown)."""
    with _POOL_LOCK:
        for pool in _POOLS.values():
            pool.closeall()
        _POOLS.clear()
    with _CONN_KEYS_LOCK:
        _CONN_KEYS.clear()
