                                    
"""
Database connection manager.
Provides a simple connection pool for PostgreSQL.
"""

import logging
import psycopg2
from contextlib import contextmanager

from ingestion.config.settings import DB_CONFIG

logger = logging.getLogger(__name__)


def get_connection():
    """Create a new database connection."""
    return psycopg2.connect(
        host=DB_CONFIG["host"],
        port=DB_CONFIG["port"],
        database=DB_CONFIG["database"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
    )


@contextmanager
def get_cursor(commit=True):
    """
    Context manager for database operations.

    Usage:
        with get_cursor() as cur:
            cur.execute("SELECT ...")
    """
    conn = get_connection()
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
        conn.close()
