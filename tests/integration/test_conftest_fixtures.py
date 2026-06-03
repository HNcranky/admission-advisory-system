import pytest

pytestmark = pytest.mark.integration


def test_db_available_fixture_lets_tests_run_when_db_is_reachable(db_available):
    """Sanity check: when DB is up, the fixture yields without skipping."""
    # If we got here, db_available did not call pytest.skip().
    assert True


def test_clean_db_truncates_canonical_records(clean_db):
    """After clean_db runs, canonical_admission_records is empty."""
    import psycopg2
    from ingestion.config.settings import DB_CONFIG

    conn = psycopg2.connect(**DB_CONFIG)
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM canonical_admission_records")
        count = cur.fetchone()[0]
    conn.close()

    assert count == 0
