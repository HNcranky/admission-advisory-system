from services.inference.models import InferenceResult
from services.policy_inference_service import interpret_policy_ambiguity


class FakeGateway:
    def run(self, request):
        return InferenceResult(
            agent_name=request.agent_name,
            model="gemini-2.5-flash",
            provider="fake",
            content='{"warnings":["Ambiguous quota wording."],"requires_human_verification":true}',
            parsed_data={
                "warnings": ["Ambiguous quota wording."],
                "requires_human_verification": True,
            },
        )


def test_interpret_policy_ambiguity_returns_structured_warning():
    parsed = interpret_policy_ambiguity(
        user_query="Chi tieu xet tuyen co thay doi khong?",
        conflicts=["Quota conflict for Khoa hoc May tinh at HUST"],
        gateway=FakeGateway(),
    )

    assert parsed["requires_human_verification"] is True
    assert parsed["warnings"] == ["Ambiguous quota wording."]


from services.inference.models import InferenceError


class _RaisingGateway:
    def is_available(self):
        return True

    def run(self, request):
        raise InferenceError("boom")


def test_policy_ambiguity_degrades_on_inference_error():
    result = interpret_policy_ambiguity("query", ["some conflict"], _RaisingGateway())
    assert result == {"warnings": [], "requires_human_verification": False}