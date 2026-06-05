import contextlib
import io
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


TEST_DB_NAME = "admission_test"


@pytest.fixture(scope="session", autouse=True)
def _isolate_test_db():
    """Redirect every in-process DB connection to the admission_test database.

    All DB code (ingestion db_connection, services/chat/db,
    services/knowledge/db, db_writer, test helpers) reads the database name
    from the shared ingestion.config.settings.DB_CONFIG dict at connect time,
    so mutating it here redirects everything. This keeps destructive test
    fixtures (TRUNCATE canonical/knowledge tables) away from the dev
    `admission` database — see
    docs/superpowers/specs/2026-06-06-test-db-isolation-design.md.

    If the Postgres server is unreachable the redirect still happens but no
    database is created; DB-dependent fixtures keep their skip behavior.
    """
    import os

    import psycopg2

    from ingestion.config.settings import DB_CONFIG

    original = DB_CONFIG["database"]
    original_env = os.environ.get("DB_NAME")
    DB_CONFIG["database"] = TEST_DB_NAME
    # Some tests importlib.reload() the settings module, which rebuilds
    # DB_CONFIG from the environment. Setting DB_NAME keeps the redirect
    # intact across reloads.
    os.environ["DB_NAME"] = TEST_DB_NAME
    try:
        try:
            probe = psycopg2.connect(
                host=DB_CONFIG["host"],
                port=DB_CONFIG["port"],
                database="postgres",
                user=DB_CONFIG["user"],
                password=DB_CONFIG["password"],
                connect_timeout=2,
            )
        except psycopg2.OperationalError:
            pass  # server down -> db_available skips with remediation
        else:
            probe.close()
            from db.setup_db import (
                create_database,
                run_migrations,
                seed_source_registry,
            )

            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                create_database()
                run_migrations()  # idempotent, mirrors `python -m db.setup_db`
                seed_source_registry()
            if "⚠" in buffer.getvalue():  # surface migration errors
                print(buffer.getvalue())
        yield
    finally:
        DB_CONFIG["database"] = original
        if original_env is None:
            os.environ.pop("DB_NAME", None)
        else:
            os.environ["DB_NAME"] = original_env
