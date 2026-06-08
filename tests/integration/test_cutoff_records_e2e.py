"""Round-trip: migration 016 → save_cutoff_records → fetch_cutoff_history.

Cần Docker DB: `docker compose up -d db && python -m db.setup_db`.
"""
from ingestion.models.pipeline_models import NormalizedCutoffRecord
from ingestion.storage.db_connection import get_cursor
from ingestion.storage.db_writer import save_cutoff_records
from services.retrieval_service import fetch_cutoff_history

_TEST_URL_A = "integration-test://cutoff/source-a"
_TEST_URL_B = "integration-test://cutoff/source-b"


def _record(year, score, source_url, trust=5):
    return NormalizedCutoffRecord(
        school_id="itest_school", program_id="itest_program",
        program_name_canonical="ITest Program", cutoff_year=year,
        admission_method="thpt_score", score_scale=30.0, cutoff_score=score,
        subject_combinations=["A00"], source_url=source_url, source_trust_level=trust,
    )


def _cleanup():
    with get_cursor() as cur:
        cur.execute("DELETE FROM cutoff_records WHERE school_id = 'itest_school'")


def test_cutoff_roundtrip_upsert_and_fetch(db_available):
    _cleanup()
    try:
        records = [
            _record(2025, 26.20, _TEST_URL_A),
            _record(2025, 26.80, _TEST_URL_B, trust=4),   # nguồn thứ hai cùng (school, program, year)
            _record(2024, 25.90, _TEST_URL_A),
        ]
        assert save_cutoff_records(records) == 3
        # Idempotent: upsert lần 2 không nhân đôi.
        assert save_cutoff_records(records) == 3

        history = fetch_cutoff_history({("itest_school", "itest_program")})
        entries = history[("itest_school", "itest_program")]
        assert len(entries) == 3                                   # per-source coexist (EC-16 nền)
        assert entries[0].cutoff_year == 2025                      # ORDER BY year DESC
        latest_scores = {e.cutoff_score for e in entries if e.cutoff_year == 2025}
        assert latest_scores == {26.20, 26.80}
    finally:
        _cleanup()
