from services.conflict.models import ComparisonReport, ConflictRecord, EvidenceOption
from services.conflict.resolution_inference_service import interpret_conflict_tiebreak
from services.inference.models import InferenceError, InferenceResult


def _record():
    return ConflictRecord(
        conflict_key="hust:2026:cs:thpt",
        field_name="quota",
        school_id="hust",
        school_name="HUST",
        admission_year=2026,
        program_name="Khoa hoc May tinh",
    )


def _report():
    return ComparisonReport(
        ranked_options=[
            EvidenceOption(evidence_id="a", source_url="https://a.test", trust_level=5, value=120),
            EvidenceOption(evidence_id="b", source_url="https://b.test", trust_level=3, value=150),
        ],
        is_decisive=False,
    )


class _Gateway:
    def __init__(self, parsed=None, exc=None):
        self._parsed = parsed
        self._exc = exc

    def is_available(self):
        return True

    def run(self, request):
        assert request.agent_name == "resolution_agent"
        assert request.output_mode == "json"
        if self._exc is not None:
            raise self._exc
        return InferenceResult(
            agent_name="resolution_agent", model="m", provider="fake",
            content="{}", parsed_data=self._parsed,
        )


def test_returns_parsed_data():
    gateway = _Gateway(parsed={"confidence": "high", "chosen_source_url": "https://a.test", "rationale": "r"})
    out = interpret_conflict_tiebreak(_record(), _report(), gateway)
    assert out["confidence"] == "high"
    assert out["chosen_source_url"] == "https://a.test"


def test_degrades_on_inference_error():
    gateway = _Gateway(exc=InferenceError("boom"))
    out = interpret_conflict_tiebreak(_record(), _report(), gateway)
    assert out == {"confidence": "low"}


def test_degrades_when_gateway_unavailable():
    class _Unavailable:
        def is_available(self):
            return False

        def run(self, request):
            raise AssertionError("should not be called")

    out = interpret_conflict_tiebreak(_record(), _report(), _Unavailable())
    assert out == {"confidence": "low"}
