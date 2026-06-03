from types import SimpleNamespace

from ingestion.knowledge.local_metadata import (
    KNOWN_SCHOOLS,
    UNKNOWN_SCHOOL,
    ResolvedMetadata,
    build_gateway_classifier,
    load_overrides,
    metadata_from_override,
    resolve_metadata,
    year_from_filename,
)
from services.inference.models import InferenceError


def test_load_overrides_missing_file_returns_empty(tmp_path):
    assert load_overrides(tmp_path) == {}


def test_load_overrides_reads_entries(tmp_path):
    (tmp_path / "overrides.json").write_text(
        '{"de-an-hust.pdf": {"school": "HUST", "year": 2026}}', encoding="utf-8"
    )
    overrides = load_overrides(tmp_path)
    assert overrides == {"de-an-hust.pdf": {"school": "HUST", "year": 2026}}


def test_metadata_from_override_maps_fields():
    meta = metadata_from_override({"school": "NEU", "year": 2025})
    assert meta == ResolvedMetadata(school="NEU", year=2025)


def test_metadata_from_override_defaults_missing_fields():
    meta = metadata_from_override({})
    assert meta.school == UNKNOWN_SCHOOL
    assert meta.year is None


def test_year_from_filename_finds_20xx():
    assert year_from_filename("de-an-tuyen-sinh-2026-final.pdf") == 2026


def test_year_from_filename_none_when_absent():
    assert year_from_filename("quy-che.pdf") is None
