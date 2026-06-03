"""E2E smoke tests: pipeline → save_canonical_records → DB query."""

import psycopg2
import pytest

from ingestion.config.settings import DB_CONFIG
from ingestion.pipeline.ingestion_pipeline import IngestionPipeline
from ingestion.storage.db_writer import save_canonical_records

pytestmark = pytest.mark.integration


def _count_vnu_uet_rows():
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM canonical_admission_records "
                "WHERE school_id = %s AND admission_year = %s",
                ("vnu_uet", 2026),
            )
            return cur.fetchone()[0]
    finally:
        conn.close()


def test_vnu_uet_pipeline_persists_twenty_canonical_records(clean_db):
    records = IngestionPipeline().run_for_school("vnu_uet")
    assert len(records) == 20, (
        f"Pipeline produced {len(records)} records, expected 20 (PDF source "
        "only after dự bị fix). If the upstream PDF changed, update this "
        "assertion."
    )

    saved = save_canonical_records(records)
    assert saved == 20

    assert _count_vnu_uet_rows() == 20


def test_canonical_records_have_per_source_unique_constraint(db_available):
    """Migration 010 must install canonical_admission_records_per_source_key.

    Without this constraint, ON CONFLICT in db_writer.py silently fails to
    upsert per-source rows.
    """
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT conname
                FROM pg_constraint
                WHERE conrelid = 'canonical_admission_records'::regclass
                  AND contype = 'u'
                """
            )
            names = {row[0] for row in cur.fetchall()}
    finally:
        conn.close()

    assert "canonical_admission_records_per_source_key" in names, (
        "Migration 010 has not been applied or the constraint name drifted. "
        "Re-run `python -m db.setup_db`."
    )
