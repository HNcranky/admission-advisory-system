from contextlib import contextmanager

import ingestion.storage.db_writer as db_writer
from ingestion.models.pipeline_models import NormalizedAdmissionRecord


def _make_record(source_url: str) -> NormalizedAdmissionRecord:
    return NormalizedAdmissionRecord(
        school_id="hust",
        school_name_canonical="Hanoi University of Science and Technology",
        admission_year=2026,
        program_id="computer_science",
        program_name_canonical="Khoa hoc may tinh",
        admission_method="thpt_score",
        source_url=source_url,
        source_trust_level=5,
        confidence_score=0.9,
    )


class _TrackingCursor:
    def __init__(self):
        self.executions: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple) -> None:
        self.executions.append((sql, params))


def test_save_canonical_records_conflict_target_includes_source_url(monkeypatch):
    cursor = _TrackingCursor()

    @contextmanager
    def fake_get_cursor(commit=True):
        yield cursor

    monkeypatch.setattr(db_writer, "get_cursor", fake_get_cursor)

    count = db_writer.save_canonical_records([_make_record("https://hust.edu.vn/admission/2026")])

    assert count == 1
    executed_sql = cursor.executions[0][0]
    normalized = " ".join(executed_sql.split())
    assert "ON CONFLICT (school_id, admission_year, program_id, admission_method, source_url)" in normalized


def test_save_canonical_records_same_source_reingest_updates_not_inserts(monkeypatch):
    """Re-ingesting the same source URL calls the cursor twice (once per call to
    save_canonical_records). The ON CONFLICT DO UPDATE handles idempotency at the
    DB level; the writer's job is just to send both executions through."""
    cursor = _TrackingCursor()

    @contextmanager
    def fake_get_cursor(commit=True):
        yield cursor

    monkeypatch.setattr(db_writer, "get_cursor", fake_get_cursor)

    record = _make_record("https://hust.edu.vn/admission/2026")
    count1 = db_writer.save_canonical_records([record])
    count2 = db_writer.save_canonical_records([record])

    assert count1 == 1
    assert count2 == 1
    assert len(cursor.executions) == 2


def test_save_canonical_records_two_distinct_sources_both_written(monkeypatch):
    """Two records with the same logical program tuple but different source_url
    values are both sent to the cursor - no writer-level deduplication."""
    cursor = _TrackingCursor()

    @contextmanager
    def fake_get_cursor(commit=True):
        yield cursor

    monkeypatch.setattr(db_writer, "get_cursor", fake_get_cursor)

    records = [
        _make_record("https://hust.edu.vn/admission/2026"),
        _make_record("https://ts.hust.edu.vn/tuyen-sinh/2026"),
    ]
    count = db_writer.save_canonical_records(records)

    assert count == 2
    assert len(cursor.executions) == 2
    source_urls_in_params = [ex[1][14] for ex in cursor.executions]
    assert "https://hust.edu.vn/admission/2026" in source_urls_in_params
    assert "https://ts.hust.edu.vn/tuyen-sinh/2026" in source_urls_in_params
