from types import SimpleNamespace

from services.inference.models import InferenceError, InferenceResult
from services.profile.extractor import extract_profile_update


def _state(**kw):
    base = dict(admission_year=None, total_score=None, subject_combination=None,
                preferred_majors=[], preferred_schools=[], location_preference=None,
                tuition_budget=None, constraints=[])
    base.update(kw)
    return SimpleNamespace(**base)


class UnavailableGateway:
    def is_available(self):
        return False

    def run(self, request):
        raise AssertionError("không được gọi LLM khi gateway unavailable / bare answer")


class FakeGatewayFields:
    def __init__(self, data):
        self._data = data
        self.calls = 0

    def is_available(self):
        return True

    def run(self, request):
        self.calls += 1
        return InferenceResult(agent_name=request.agent_name, model="f", provider="f",
                               content="{}", parsed_data=self._data)


class FailingGateway:
    def is_available(self):
        return True

    def run(self, request):
        raise InferenceError("llm down")


def _no_majors(text, **kw):
    return []


def test_deterministic_active_slot_bare_answer_skips_llm():
    delta = extract_profile_update(
        "29", known_state=_state(admission_year=2026), active_slot="total_score",
        gateway=UnavailableGateway(), resolver=_no_majors)
    assert delta == {"total_score": 29.0}


def test_resolver_supplies_preferred_majors():
    delta = extract_profile_update(
        "em thích làm app", known_state=_state(), active_slot="preferred_majors",
        gateway=UnavailableGateway(), resolver=lambda text, **kw: ["software_engineering"])
    assert delta["preferred_majors"] == ["software_engineering"]


def test_llm_fills_other_slots_as_delta():
    gw = FakeGatewayFields({"location_preference": "Ha Noi", "subject_combination": "A00"})
    delta = extract_profile_update(
        "mình muốn học ở Hà Nội khối A00", known_state=_state(), active_slot=None,
        gateway=gw, resolver=_no_majors)
    assert delta["location_preference"] == "Ha Noi"
    assert delta["subject_combination"] == "A00"
    assert gw.calls == 1


def test_llm_failure_degrades_to_deterministic_delta():
    delta = extract_profile_update(
        "năm 2026", known_state=_state(), active_slot="admission_year",
        gateway=FailingGateway(), resolver=_no_majors)
    assert delta == {"admission_year": 2026}  # Tier-0 vẫn có, LLM lỗi bị nuốt


def test_llm_output_strips_majors_and_unknown_keys():
    gw = FakeGatewayFields({"preferred_majors": ["xxx"], "garbage": 1, "total_score": 30.0})
    delta = extract_profile_update(
        "mình được 30 điểm", known_state=_state(), active_slot=None,
        gateway=gw, resolver=_no_majors)
    assert delta == {"total_score": 30.0}  # preferred_majors (do resolver lo) & key lạ bị loại
