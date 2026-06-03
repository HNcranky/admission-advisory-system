import services.profile_inference_service as pis
from services.inference.models import InferenceResult


class FakeGateway:
    def is_available(self):
        return True

    def run(self, request):
        # LLM KHÔNG còn trả preferred_majors (id) nữa — chỉ các slot khác.
        return InferenceResult(
            agent_name=request.agent_name, model="fake", provider="fake",
            content="{}", parsed_data={"total_score": 26.0},
        )


def test_extraction_uses_resolver_for_majors(monkeypatch):
    monkeypatch.setattr(pis, "resolve_majors",
                        lambda text, **kw: ["software_engineering"])
    profile = pis.build_profile_with_gateway("em thích làm app", FakeGateway())
    assert profile.preferred_majors == ["software_engineering"]
    assert profile.total_score == 26.0
    assert "preferred_majors" not in profile.missing_slots


def test_no_hardcoded_major_maps_remain():
    assert not hasattr(pis, "INTEREST_MAJOR_MAP")
    assert not hasattr(pis, "MAJOR_ID_GUIDE")
