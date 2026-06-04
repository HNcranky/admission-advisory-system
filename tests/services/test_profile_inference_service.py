from services.profile.slots import SLOTS
from services.profile_inference_service import (
    PROFILE_SYSTEM_PROMPT,
    build_profile_with_gateway,
)
from services.inference.models import InferenceResult


class FakeGateway:
    def run(self, request):
        return InferenceResult(
            agent_name=request.agent_name,
            model="gemini-2.5-flash-lite",
            provider="fake",
            content='{"total_score":27,"subject_combination":"A00","preferred_majors":["computer_science"],"preferred_schools":["hust"],"missing_slots":[]}',
            parsed_data={
                "total_score": 27,
                "subject_combination": "A00",
                "preferred_majors": ["computer_science"],
                "preferred_schools": ["hust"],
                "missing_slots": [],
            },
        )


def test_profile_system_prompt_covers_every_chat_critical_slot():
    # admission_year is extracted by regex in the chat layer, not by the LLM,
    # so the extraction prompt only needs to mention the slots the LLM owns.
    critical_slots = [slot.name for slot in SLOTS if slot.critical]
    llm_owned_slots = [slot for slot in critical_slots if slot != "admission_year"]
    for slot in llm_owned_slots:
        assert slot in PROFILE_SYSTEM_PROMPT, (
            f"PROFILE_SYSTEM_PROMPT must mention '{slot}' so live Gemini can fill it "
            "(otherwise the chat layer loops asking for that slot)."
        )


def test_profile_system_prompt_delegates_majors_to_resolver():
    # Slice 2: majors are resolved from a DB-backed catalog via the tiered
    # resolver, not inferred by the extraction prompt. The prompt must not
    # hardcode any program ids and should tell the model it doesn't need to
    # return preferred_majors (that is now the resolver's job).
    assert "KHÔNG cần trả preferred_majors" in PROFILE_SYSTEM_PROMPT
    assert "artificial_intelligence_uet" not in PROFILE_SYSTEM_PROMPT
    assert "infer suitable related majors" not in PROFILE_SYSTEM_PROMPT


def test_build_profile_with_gateway_returns_student_profile():
    profile = build_profile_with_gateway(
        user_query="Em duoc 27 diem A00 muon hoc Cong nghe thong tin o HUST",
        gateway=FakeGateway(),
    )

    assert profile.total_score == 27
    assert profile.subject_combination == "A00"
    # Majors no longer come from the LLM payload — the tiered resolver derives
    # them from the query. "Cong nghe thong tin" is an alias for this id.
    assert profile.preferred_majors == ["information_technology_uet"]
    assert profile.preferred_schools == ["hust"]


def test_build_profile_with_gateway_falls_back_when_gateway_is_unavailable():
    class UnavailableGateway:
        def is_available(self):
            return False

        def run(self, request):
            raise AssertionError("gateway.run should not be called when unavailable")

    profile = build_profile_with_gateway(
        user_query="Em duoc 27 diem A00 muon hoc Cong nghe thong tin o HUST",
        gateway=UnavailableGateway(),
    )

    assert profile.total_score == 27
    assert profile.subject_combination == "A00"
    # Even on the rule-based fallback path, majors come from the resolver
    # (Tier1 alias) running on the query.
    assert profile.preferred_majors == ["information_technology_uet"]
    assert profile.preferred_schools == ["hust"]
    # missing_slots now comes from the registry critical set; admission_method
    # is a new critical slot (location_preference is no longer critical — spec mục 8).
    assert profile.missing_slots == ["admission_year", "admission_method"]


def test_natural_interest_query_resolves_majors_via_resolver():
    # Slice 2 (G1): natural-interest phrasing maps to program ids through the
    # tiered resolver, NOT the removed hardcoded INTEREST_MAJOR_MAP. Any raw
    # major strings the LLM might still emit are discarded; the resolver owns
    # majors. "trí tuệ nhân tạo" is an alias for artificial_intelligence_uet.
    class NaturalInterestGateway:
        def run(self, request):
            return InferenceResult(
                agent_name=request.agent_name,
                model="gemini-2.5-flash-lite",
                provider="fake",
                content='{"total_score":26.5,"subject_combination":"A00","preferred_majors":["lập trình","trí tuệ nhân tạo"],"preferred_schools":["vnu_uet"],"missing_slots":[]}',
                parsed_data={
                    "total_score": 26.5,
                    "subject_combination": "A00",
                    "preferred_majors": ["lập trình", "trí tuệ nhân tạo"],
                    "preferred_schools": ["vnu_uet"],
                    "missing_slots": [],
                },
            )

    profile = build_profile_with_gateway(
        user_query="Em thích lập trình và trí tuệ nhân tạo, muốn học ở UET",
        gateway=NaturalInterestGateway(),
    )

    # Raw LLM interest strings are gone; resolver-derived id is present.
    assert profile.preferred_majors == ["artificial_intelligence_uet"]
    assert "lập trình" not in profile.preferred_majors
    assert profile.total_score == 26.5


from services.inference.models import InferenceError


class _RaisingGateway:
    def is_available(self):
        return True

    def run(self, request):
        raise InferenceError("boom")


def test_build_profile_degrades_to_rule_based_on_inference_error():
    profile = build_profile_with_gateway("Em duoc 27 diem khoi A00", _RaisingGateway())
    # Rule-based fallback still extracts the score from the query.
    assert profile.total_score == 27
