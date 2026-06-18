import psycopg2
import pytest

from ingestion.config.settings import DB_CONFIG

pytestmark = pytest.mark.integration


def _fetch_scalar(sql, params=None):
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchone()[0]
    finally:
        conn.close()


def test_qa_cache_tables_exist(db_available):
    for table in ("knowledge_qa_cache", "knowledge_qa_cache_version"):
        assert _fetch_scalar(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = %s",
            (table,),
        ) == 1, f"missing table {table}"


def test_qa_cache_indexes_exist(db_available):
    for index in (
        "idx_qa_cache_scope",
        "idx_qa_cache_embedding",
        "idx_qa_cache_expires",
    ):
        assert _fetch_scalar(
            "SELECT COUNT(*) FROM pg_indexes "
            "WHERE schemaname = 'public' AND indexname = %s",
            (index,),
        ) == 1, f"missing index {index}"


def test_qa_cache_embedding_is_768_dim_vector(db_available):
    atttypmod = _fetch_scalar(
        """
        SELECT a.atttypmod
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        WHERE c.relname = 'knowledge_qa_cache' AND a.attname = 'embedding'
        """
    )
    assert atttypmod == 768
