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


# --- resolve_metadata -----------------------------------------------------------

class FakeGateway:
    """Gateway giả: trả parsed_data cho sẵn hoặc raise InferenceError."""

    def __init__(self, parsed=None, exc=None):
        self.requests = []
        self._parsed = parsed
        self._exc = exc

    def run(self, request):
        self.requests.append(request)
        if self._exc is not None:
            raise self._exc
        return SimpleNamespace(parsed_data=self._parsed, content="")


def test_override_wins_without_llm_call():
    gw = FakeGateway(parsed={"school": "HUST", "year": 2026})
    overrides = {"x.pdf": {"school": "NEU", "year": 2024}}

    meta = resolve_metadata("text trang đầu", "x.pdf", overrides, gw)

    assert meta.school == "NEU" and meta.year == 2024
    assert gw.requests == []                  # không tốn call classify


def test_classify_returns_school_and_year():
    gw = FakeGateway(parsed={"school": "VNU-UET", "year": 2026})

    meta = resolve_metadata("ĐẠI HỌC CÔNG NGHỆ ...", "de-an.pdf", {}, gw)

    assert meta.school == "VNU-UET" and meta.year == 2026
    assert meta.warnings == []
    req = gw.requests[0]
    assert req.agent_name == "knowledge_classify"
    assert req.task_type == "local_pdf_metadata"
    assert req.output_mode == "json"
    assert "de-an.pdf" in req.user_prompt
    assert "ĐẠI HỌC CÔNG NGHỆ" in req.user_prompt


def test_school_outside_whitelist_becomes_unknown_with_warning():
    gw = FakeGateway(parsed={"school": "FTU", "year": 2026})

    meta = resolve_metadata("text", "ftu.pdf", {}, gw)

    assert meta.school == UNKNOWN_SCHOOL
    assert meta.year == 2026                  # year hợp lệ vẫn giữ
    assert any("ftu.pdf" in w and "overrides.json" in w for w in meta.warnings)


def test_year_falls_back_to_filename_when_classify_unsure():
    gw = FakeGateway(parsed={"school": "HUST", "year": None})

    meta = resolve_metadata("text", "de-an-2026.pdf", {}, gw)

    assert meta.school == "HUST"
    assert meta.year == 2026                  # regex \b20\d{2}\b từ tên file


def test_year_string_from_llm_is_coerced_to_int():
    gw = FakeGateway(parsed={"school": "HUST", "year": "2025"})

    meta = resolve_metadata("text", "x.pdf", {}, gw)

    assert meta.year == 2025


def test_inference_error_degrades_to_unknown_school():
    gw = FakeGateway(exc=InferenceError("boom"))

    meta = resolve_metadata("text", "de-an-2026.pdf", {}, gw)

    assert meta.school == UNKNOWN_SCHOOL
    assert meta.year == 2026                  # filename fallback vẫn chạy
    assert len(meta.warnings) == 1


def test_structure_failure_parsed_none_degrades_like_empty():
    gw = FakeGateway(parsed=None)             # gateway đã hết retry, JSON vẫn hỏng

    meta = resolve_metadata("text", "x.pdf", {}, gw)

    assert meta.school == UNKNOWN_SCHOOL
    assert meta.year is None


# --- build_gateway_classifier -----------------------------------------------------

def test_build_gateway_classifier_binds_gateway():
    gw = FakeGateway(parsed={"school": "HUST", "year": 2026})
    classify = build_gateway_classifier(gateway=gw)

    meta = classify("text trang 1", "x.pdf", {})

    assert meta == ResolvedMetadata(school="HUST", year=2026)
    assert len(gw.requests) == 1


def test_build_gateway_classifier_callable_honors_overrides():
    gw = FakeGateway(parsed={"school": "HUST", "year": 2026})
    classify = build_gateway_classifier(gateway=gw)

    meta = classify("text", "x.pdf", {"x.pdf": {"school": "NEU", "year": 2024}})

    assert meta.school == "NEU"
    assert gw.requests == []
