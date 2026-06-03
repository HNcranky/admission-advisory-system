from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_per_source_migration_exists_and_uses_source_url():
    migration = ROOT / "db" / "migrations" / "010_canonical_records_per_source.sql"
    sql = migration.read_text(encoding="utf-8")

    assert "canonical_admission_records" in sql
    assert "source_url" in sql
    assert "school_id, admission_year, program_id, admission_method, source_url" in sql


def test_db_writer_upserts_per_source_key():
    writer = ROOT / "ingestion" / "storage" / "db_writer.py"
    source = writer.read_text(encoding="utf-8")

    assert (
        "ON CONFLICT (school_id, admission_year, program_id, admission_method, source_url)"
        in source
    )
