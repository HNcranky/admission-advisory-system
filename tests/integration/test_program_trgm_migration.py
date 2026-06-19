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


def test_pg_trgm_extension_installed(db_available):
    assert _fetch_scalar(
        "SELECT COUNT(*) FROM pg_extension WHERE extname = 'pg_trgm'"
    ) == 1


def test_program_trgm_index_exists(db_available):
    assert _fetch_scalar(
        "SELECT COUNT(*) FROM pg_indexes "
        "WHERE schemaname = 'public' AND indexname = %s",
        ("idx_knowledge_chunks_program_trgm",),
    ) == 1


def test_word_similarity_callable(db_available):
    # Proves pg_trgm's word_similarity is available for resolve_program.
    assert _fetch_scalar("SELECT word_similarity(%s, %s) > 0",
                         ("ô tô", "ngành kỹ thuật ô tô")) is True
