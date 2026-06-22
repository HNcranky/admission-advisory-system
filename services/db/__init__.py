"""Shared DB helpers: 1 cursor context manager + pgvector literal builder.

Gom từ 4 bản _cursor copy-paste + 2 bản _vector_literal trong services/.
Hành vi y hệt bản cũ: commit khi commit=True, rollback + re-raise khi lỗi,
cur.close() rồi release(conn) trong finally.
"""
from contextlib import contextmanager
from typing import Optional

from services.db.pool import release


@contextmanager
def cursor(connection_factory, commit: bool = False):
    conn = connection_factory()
    try:
        cur = conn.cursor()
        try:
            yield cur
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
    finally:
        release(conn)


def vector_literal(embedding) -> Optional[str]:
    if embedding is None:
        return None
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"
