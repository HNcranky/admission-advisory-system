"""Unit tests for the gateway-routed llm_extract (audit §2.1 / plan PR10).

Uses a FakeGateway so no network / API key is needed.
"""
from ingestion.extractors.llm_extractor import llm_extract
from ingestion.models.pipeline_models import ParsedContent, SourceReference
from services.inference.models import InferenceError, InferenceResult


class _FakeGateway:
    def __init__(self, result=None, exc=None):
        self._result = result
        self._exc = exc
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        if self._exc:
            raise self._exc
        return self._result


def _result(parsed):
    return InferenceResult(
        agent_name="fact_extractor", model="fake", provider="fake",
        content="{}", parsed_data=parsed,
    )


def _dummy_parsed():
    return ParsedContent(
        text="Trường Đại học Bách khoa Hà Nội tuyển sinh ngành Công nghệ thông tin "
             "năm 2026 theo phương thức xét điểm thi tốt nghiệp THPT, chỉ tiêu 100."
    )


def _dummy_source_ref():
    return SourceReference(
        source_id="hust_test", source_url="https://ts.hust.edu.vn/", school_id="hust",
    )


def test_llm_extract_maps_gateway_json_to_facts():
    parsed_json = {"facts": [{"program_name": "CNTT", "program_code": "IT1",
                              "admission_method_raw": "THPT", "quota_raw": "100"}]}
    gw = _FakeGateway(result=_result(parsed_json))

    facts = llm_extract(_dummy_parsed(), _dummy_source_ref(), "HUST", gateway=gw)

    assert facts and facts[0].program_code == "IT1"
    assert facts[0].extraction_method == "llm_gemini"
    assert gw.requests[0].agent_name == "fact_extractor"
    assert gw.requests[0].output_mode == "json"


def test_llm_extract_returns_empty_on_inference_error():
    gw = _FakeGateway(exc=InferenceError("boom"))
    assert llm_extract(_dummy_parsed(), _dummy_source_ref(), "HUST", gateway=gw) == []


def test_llm_extract_returns_empty_when_no_parsed_data():
    gw = _FakeGateway(result=_result(None))
    assert llm_extract(_dummy_parsed(), _dummy_source_ref(), "HUST", gateway=gw) == []


def test_llm_extract_returns_empty_for_short_text():
    gw = _FakeGateway(result=_result({"facts": []}))
    parsed = ParsedContent(text="too short")
    assert llm_extract(parsed, _dummy_source_ref(), "HUST", gateway=gw) == []
    assert gw.requests == []  # never called the gateway
