"""Synthetic failure scenarios for the inference gateway.

The gateway (`services/inference/gateway.py`) is the single choke point every LLM
call passes through, so its retry/fallback behavior is what keeps a transient
Gemini failure from surfacing to the student. These scenarios drive the *real*
`LLMGateway.run` — only the provider is mocked, so the retry loop, the
STRUCTURE_FAILURE branch, and the fallback branch all execute exactly as in
production. No network and no Gemini key are needed.

Each scenario scripts a sequence of provider behaviors (one per `generate` call
the gateway makes), wires a matching policy via `ModelRegistry`, runs the
gateway, and classifies the outcome as recovered or not.
"""

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from services.inference.gateway import LLMGateway
from services.inference.models import (
    InferenceError,
    InferenceRequest,
    InferenceResult,
)
from services.inference.registry import ModelRegistry

PRIMARY = "gemini-2.5-flash"
FALLBACK = "gemini-2.5-flash-lite"


def _clean(model: str) -> InferenceResult:
    return InferenceResult(
        agent_name="reliability_probe",
        model=model,
        provider="gemini",
        content='{"ok": true}',
        parsed_data={"ok": True},
        failure_type=None,
    )


def _structure_failure(model: str) -> InferenceResult:
    """A malformed-JSON response: the provider returns, but the payload could not
    be parsed into the requested schema, so the gateway sees STRUCTURE_FAILURE."""
    return InferenceResult(
        agent_name="reliability_probe",
        model=model,
        provider="gemini",
        content="{invalid json",
        parsed_data=None,
        failure_type="STRUCTURE_FAILURE",
    )


def _api_error(_model: str) -> InferenceError:
    """A hard API failure: timeout / 5xx / rate limit / auth — the provider
    raises before producing any result."""
    return InferenceError("simulated API failure (timeout / 5xx)")


class ScriptedProvider:
    """Mock provider whose `generate` replays one scripted behavior per call.

    A behavior is a callable taking the model name and returning either an
    `InferenceResult` (which the gateway inspects for `failure_type`) or an
    `InferenceError` instance (which is raised, mimicking a hard API failure).
    """

    def __init__(self, behaviors: List[Callable[[str], object]]):
        self._behaviors = list(behaviors)
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def generate(self, request, policy):
        behavior = self._behaviors[min(self.calls, len(self._behaviors) - 1)]
        self.calls += 1
        outcome = behavior(policy.primary_model)
        if isinstance(outcome, InferenceError):
            raise outcome
        return outcome


@dataclass
class Scenario:
    key: str
    family: str  # "api_fallback" | "structured_output" | "degradation_contract"
    description: str
    behaviors: List[Callable[[str], object]]
    allow_fallback: bool
    max_retries: int = 1
    # Given (result, error) from the gateway, did the system recover as designed?
    recovered: Callable[[Optional[InferenceResult], Optional[Exception]], bool] = field(
        default=lambda r, e: r is not None and r.failure_type is None
    )


def _recovered_clean(result, error):
    return error is None and result is not None and result.failure_type is None


def _contract_honored(result, error):
    # No fallback configured: the documented contract is that the gateway
    # surfaces InferenceError so the call site can degrade deterministically.
    return isinstance(error, InferenceError)


SCENARIOS: List[Scenario] = [
    Scenario(
        key="api_timeout_fallback",
        family="api_fallback",
        description="Primary model times out (hard API error); fallback model answers.",
        behaviors=[_api_error, _clean],
        allow_fallback=True,
        recovered=_recovered_clean,
    ),
    Scenario(
        key="api_5xx_fallback",
        family="api_fallback",
        description="Primary model returns 5xx on every attempt; fallback model answers.",
        behaviors=[_api_error, _clean],
        allow_fallback=True,
        recovered=_recovered_clean,
    ),
    Scenario(
        key="malformed_json_retry",
        family="structured_output",
        description="Primary returns malformed JSON once, then valid JSON on retry.",
        behaviors=[_structure_failure, _clean],
        allow_fallback=False,
        max_retries=1,
        recovered=_recovered_clean,
    ),
    Scenario(
        key="malformed_json_fallback",
        family="structured_output",
        description="Primary returns malformed JSON on every retry; fallback returns valid JSON.",
        behaviors=[_structure_failure, _structure_failure, _clean],
        allow_fallback=True,
        max_retries=1,
        recovered=_recovered_clean,
    ),
    Scenario(
        key="api_error_no_fallback_degrades",
        family="degradation_contract",
        description="Hard API error with no fallback: gateway surfaces InferenceError "
        "so the call site degrades to deterministic output.",
        behaviors=[_api_error],
        allow_fallback=False,
        recovered=_contract_honored,
    ),
]


def run_scenario(scenario: Scenario):
    """Execute one scenario against the real gateway and return (recovered, detail)."""
    overrides = {
        "reliability_probe": {
            "primary_model": PRIMARY,
            "fallback_model": FALLBACK if scenario.allow_fallback else None,
            "allow_fallback": scenario.allow_fallback,
            "max_retries": scenario.max_retries,
        }
    }
    registry = ModelRegistry(default_model=PRIMARY, agent_overrides=overrides)
    provider = ScriptedProvider(scenario.behaviors)
    gateway = LLMGateway(registry=registry, providers={"gemini": provider})

    request = InferenceRequest(
        agent_name="reliability_probe",
        task_type="reliability_probe",
        system_prompt="probe",
        user_prompt="probe",
        output_mode="json",
    )

    result = None
    error = None
    try:
        result = gateway.run(request)
    except Exception as exc:  # noqa: BLE001 - we classify it below
        error = exc

    recovered = scenario.recovered(result, error)
    detail = {
        "key": scenario.key,
        "family": scenario.family,
        "provider_calls": provider.calls,
        "used_fallback": bool(result and result.model == FALLBACK),
        "result_failure_type": (result.failure_type if result else None),
        "error": type(error).__name__ if error else None,
        "recovered": recovered,
    }
    return recovered, detail
