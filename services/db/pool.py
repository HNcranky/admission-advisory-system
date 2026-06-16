"""Process-level connection pool registry keyed by DSN tuple.

When DB_POOL_ENABLED=true, each connection factory (services/chat/db.py,
services/knowledge/db.py, ingestion/storage/db_connection.py) calls lease()
instead of psycopg2.connect(). The cursor() context manager in services/db/__init__.py
calls release() in its finally block so pooled connections are returned rather
than closed. When DB_POOL_ENABLED=false, release() falls back to conn.close()
and behaviour is byte-for-byte identical to before."""

import threading

import psycopg2
from psycopg2.pool import ThreadedConnectionPool

from ingestion.config.settings import DB_POOL_MIN, DB_POOL_MAX

_POOLS: dict[tuple, ThreadedConnectionPool] = {}
_LOCK = threading.Lock()
_TAG = "_advisory_pool_key"


def _key(dsn: dict) -> tuple:
    return (dsn["host"], dsn["port"], dsn["database"], dsn["user"])


def lease(dsn: dict):
    """Return a connection from the pool for this DSN, creating the pool if needed."""
    k = _key(dsn)
    with _LOCK:
        pool = _POOLS.get(k)
        if pool is None:
            pool = ThreadedConnectionPool(
                DB_POOL_MIN, DB_POOL_MAX,
                host=dsn["host"], port=dsn["port"], dbname=dsn["database"],
                user=dsn["user"], password=dsn["password"],
            )
            _POOLS[k] = pool
    conn = pool.getconn()
    setattr(conn, _TAG, k)
    return conn


def release(conn) -> None:
    """Return conn to its pool, or close it if it was not pooled."""
    key = getattr(conn, _TAG, None)
    if key is None:
        conn.close()
        return
    with _LOCK:
        pool = _POOLS.get(key)
    if pool is None:
        conn.close()
    else:
        pool.putconn(conn)


def close_all() -> None:
    """Close every pool (useful in tests and graceful shutdown)."""
    with _LOCK:
        for pool in _POOLS.values():
            pool.closeall()
        _POOLS.clear()
