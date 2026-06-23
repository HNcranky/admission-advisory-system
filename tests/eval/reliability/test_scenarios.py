"""The reliability scenarios drive the real gateway with a mocked provider, so
they run in the normal suite with no network. Every scripted failure mode must
recover as designed."""

from eval.reliability.scenarios import SCENARIOS, run_scenario


def test_every_scenario_recovers():
    for scenario in SCENARIOS:
        recovered, detail = run_scenario(scenario)
        assert recovered, f"{scenario.key} did not recover: {detail}"


def test_api_failure_uses_fallback():
    scenario = next(s for s in SCENARIOS if s.key == "api_timeout_fallback")
    recovered, detail = run_scenario(scenario)
    assert recovered
    assert detail["used_fallback"] is True


def test_no_fallback_surfaces_inference_error():
    scenario = next(s for s in SCENARIOS if s.key == "api_error_no_fallback_degrades")
    recovered, detail = run_scenario(scenario)
    assert recovered
    assert detail["error"] == "InferenceError"
