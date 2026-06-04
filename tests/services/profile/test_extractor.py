from types import SimpleNamespace

from services.inference.models import InferenceError, InferenceResult
from services.profile.extractor import extract_profile_update


def _state(**kw):
    base = dict(admission_year=None, total_score=None, subject_combination=None,
                admission_method=None,
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


def test_resolver_supplies_explicit_majors_when_answering_major_slot():
    # Trả lời đúng câu hỏi ngành → explicit, phát op tích luỹ {"__add__": ...}.
    delta = extract_profile_update(
        "em thích làm app", known_state=_state(), active_slot="preferred_majors",
        gateway=UnavailableGateway(), resolver=lambda text, **kw: ["software_engineering"])
    assert delta["explicit_preferred_majors"] == {"__add__": ["software_engineering"]}
    assert "preferred_majors" not in delta  # view dẫn xuất tính ở apply_profile_delta


def test_vague_interest_yields_inferred_tags():
    # "thích ... AI" = sở thích suy luận → inferred_interest_tags.
    delta = extract_profile_update(
        "em thích lập trình với AI", known_state=_state(), active_slot="admission_year",
        gateway=UnavailableGateway(), resolver=lambda text, **kw: ["data_science"])
    assert delta["inferred_interest_tags"] == {"__add__": ["data_science"]}


def test_non_major_bare_answer_runs_resolver_cheap_only():
    # Trả lời tổ hợp (slot non-major đã điền) → resolver chỉ chạy Tier-1 (cheap_only=True),
    # không để embedding suy ngành tiếp tuyến gây nhiễu inferred tags.
    seen = {}

    def spy(text, **kw):
        seen["cheap_only"] = kw.get("cheap_only")
        return []

    delta = extract_profile_update(
        "A00", known_state=_state(admission_year=2026, total_score=27.0),
        active_slot="subject_combination", gateway=UnavailableGateway(), resolver=spy)
    assert delta == {"subject_combination": "A00"}
    assert seen["cheap_only"] is True


def test_initial_interest_message_runs_full_resolver():
    # Lượt đầu nêu sở thích trong khi đang hỏi năm → KHÔNG cheap_only (cho phép Tier-2/3).
    seen = {}

    def spy(text, **kw):
        seen["cheap_only"] = kw.get("cheap_only")
        return []

    extract_profile_update(
        "em thích lập trình với AI", known_state=_state(),
        active_slot="admission_year", gateway=UnavailableGateway(), resolver=spy)
    assert seen["cheap_only"] is False


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


def test_llm_admission_method_display_name_is_coerced_to_code():
    # LLM hay trả display tiếng Việt thay vì mã → coerce qua parser.
    gw = FakeGatewayFields({"admission_method": "học bạ"})
    delta = extract_profile_update(
        "em xét học bạ nhé", known_state=_state(), active_slot=None,
        gateway=gw, resolver=_no_majors)
    assert delta["admission_method"] == "school_record"


def test_llm_admission_method_garbage_is_dropped():
    gw = FakeGatewayFields({"admission_method": "phương thức vũ trụ"})
    delta = extract_profile_update(
        "abc", known_state=_state(), active_slot=None,
        gateway=gw, resolver=_no_majors)
    assert "admission_method" not in delta


def test_deterministic_method_bare_answer_skips_llm():
    delta = extract_profile_update(
        "điểm thi THPT", known_state=_state(admission_year=2026, total_score=27.0),
        active_slot="admission_method", gateway=UnavailableGateway(), resolver=_no_majors)
    assert delta == {"admission_method": "thpt_score"}
