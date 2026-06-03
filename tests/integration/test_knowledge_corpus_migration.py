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


def test_vector_extension_installed(db_available):
    assert _fetch_scalar(
        "SELECT COUNT(*) FROM pg_extension WHERE extname = 'vector'"
    ) == 1


def test_knowledge_tables_exist(db_available):
    for table in ("knowledge_documents", "knowledge_chunks"):
        assert _fetch_scalar(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = %s",
            (table,),
        ) == 1, f"missing table {table}"


def test_metadata_and_vector_indexes_exist(db_available):
    for index in (
        "idx_knowledge_chunks_school_topic",
        "idx_knowledge_chunks_embedding",
    ):
        assert _fetch_scalar(
            "SELECT COUNT(*) FROM pg_indexes "
            "WHERE schemaname = 'public' AND indexname = %s",
            (index,),
        ) == 1, f"missing index {index}"


def test_embedding_column_is_768_dim_vector(db_available):
    # pgvector stores the dimension in pg_attribute.atttypmod for the column.
    atttypmod = _fetch_scalar(
        """
        SELECT a.atttypmod
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        WHERE c.relname = 'knowledge_chunks' AND a.attname = 'embedding'
        """
    )
    assert atttypmod == 768
