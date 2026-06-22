from ingestion.models.pipeline_models import ExtractedAdmissionFact, SourceReference
import ingestion.normalization.normalizer as nz


def _fact():
    return ExtractedAdmissionFact(
        school_name="Đại học X", admission_year=2025,
        program_name="Khoa học Máy tính", program_code="IT1",
        admission_method_raw="Xét điểm THPT",
        subject_combinations_raw=["A00"], quota_raw="300",
        source_reference=SourceReference(source_id="s", source_url="http://e.com",
                                         school_id="hust", trust_level=5),
        confidence_score=0.8,
    )


def test_normalize_fact_passes_through_core_fields():
    rec = nz.normalize_fact(_fact(), school_id="hust")
    assert rec.admission_year == 2025
    assert rec.quota is not None and rec.quota.value == 300
    assert rec.program_name_raw == "Khoa học Máy tính"
