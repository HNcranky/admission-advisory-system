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


from services.conflict.resolution_inference_service import batch_interpret_conflict_tiebreak


def _record2():
    return ConflictRecord(
        conflict_key="hust:2026:ee:thpt", field_name="quota", school_id="hust",
        school_name="HUST", admission_year=2026, program_name="Ky thuat Dien",
    )


def test_batch_returns_decisions_keyed_by_conflict_key():
    gateway = _Gateway(parsed={"decisions": [
        {"conflict_key": "hust:2026:cs:thpt", "confidence": "high",
         "chosen_source_url": "https://a.test", "rationale": "r1"},
        {"conflict_key": "hust:2026:ee:thpt", "confidence": "low",
         "chosen_source_url": "https://b.test", "rationale": "r2"},
    ]})
    out = batch_interpret_conflict_tiebreak(
        [(_record(), _report()), (_record2(), _report())], gateway
    )
    assert out["hust:2026:cs:thpt"]["confidence"] == "high"
    assert out["hust:2026:ee:thpt"]["chosen_source_url"] == "https://b.test"


def test_batch_empty_pairs_makes_no_call():
    class _Boom:
        def is_available(self):
            return True

        def run(self, request):
            raise AssertionError("must not call gateway for empty batch")

    assert batch_interpret_conflict_tiebreak([], _Boom()) == {}


def test_batch_degrades_on_inference_error():
    gateway = _Gateway(exc=InferenceError("boom"))
    out = batch_interpret_conflict_tiebreak([(_record(), _report())], gateway)
    assert out == {}


def test_batch_degrades_when_gateway_unavailable():
    class _Unavailable:
        def is_available(self):
            return False

        def run(self, request):
            raise AssertionError("should not be called")

    out = batch_interpret_conflict_tiebreak([(_record(), _report())], _Unavailable())
    assert out == {}


def test_batch_skips_entries_missing_conflict_key():
    gateway = _Gateway(parsed={"decisions": [
        {"confidence": "high", "chosen_source_url": "https://a.test"},   # no conflict_key
        {"conflict_key": "hust:2026:cs:thpt", "confidence": "high",
         "chosen_source_url": "https://a.test", "rationale": "r"},
    ]})
    out = batch_interpret_conflict_tiebreak([(_record(), _report())], gateway)
    assert list(out.keys()) == ["hust:2026:cs:thpt"]
