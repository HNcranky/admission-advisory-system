"""Fixtures for integration tests that need a live Postgres DB.

The DB is expected to be running in Docker (`docker compose up -d db`) with
the schema applied (`python -m db.setup_db`). Tests using `db_available`
auto-skip with a clear remediation message if the DB is unreachable so the
suite stays green for DB-less development and CI.
"""

import psycopg2
import pytest

from ingestion.config.settings import DB_CONFIG


def _remediation() -> str:
    # Built lazily so it reflects the test-DB redirect done in tests/conftest.py.
    return (
        "Postgres not reachable at "
        f"{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}. "
        "Run `docker compose up -d db` first (the test database is created "
        "and migrated automatically)."
    )


@pytest.fixture(scope="session")
def db_available(_isolate_test_db):
    """Skip the test session unless Postgres is reachable.

    Depends on `_isolate_test_db` (tests/conftest.py) so the connection —
    and every later one in the process — targets the admission_test
    database, never the dev store. Scoped to the session so we pay the
    connection cost at most once per run.
    """
    try:
        conn = psycopg2.connect(**DB_CONFIG, connect_timeout=2)
    except psycopg2.OperationalError:
        pytest.skip(_remediation())
    else:
        conn.close()


@pytest.fixture
def clean_db(db_available):
    """Truncate canonical_admission_records before each test.

    `source_registry` is intentionally NOT truncated — it is seed data that
    the pipeline assumes is already present.
    """
    # Defense in depth: never let this TRUNCATE near the dev database.
    assert DB_CONFIG["database"].endswith("_test"), (
        f"clean_db would truncate {DB_CONFIG['database']!r} — refusing; "
        "it must only run against the isolated test database."
    )
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "TRUNCATE canonical_admission_records "
                "RESTART IDENTITY CASCADE"
            )
        conn.commit()
    finally:
        conn.close()
    yield
