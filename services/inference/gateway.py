from services.inference.models import InferenceError
from services.inference.providers.gemini_provider import GeminiProvider


class LLMGateway:
    def __init__(self, registry, providers=None, telemetry=None):
        self.registry = registry
        self.providers = providers or {"gemini": GeminiProvider()}
        self.telemetry = telemetry

    def is_available(self) -> bool:
        provider = self.providers["gemini"]
        is_available = getattr(provider, "is_available", None)
        return True if is_available is None else bool(is_available())

    def run(self, request):
        policy = self.registry.resolve(request.agent_name)
        provider = self.providers["gemini"]

        result = None
        primary_error = None
        for attempt in range(policy.max_retries + 1):
            try:
                result = provider.generate(request, policy)
            except InferenceError as exc:
                # Hard API failure (network, auth, rate limit, 5xx). Retrying the
                # same model rarely helps, so stop and let fallback try instead.
                primary_error = exc
                self._record(request, policy.primary_model, attempt, "API_ERROR", used_fallback=False)
                break
            self._record(request, policy.primary_model, attempt, result.failure_type, used_fallback=False)
            if result.failure_type != "STRUCTURE_FAILURE":
                return result

        if policy.allow_fallback and policy.fallback_model:
            fallback_policy = policy.model_copy(update={"primary_model": policy.fallback_model})
            try:
                result = provider.generate(request, fallback_policy)
            except InferenceError as exc:
                self._record(
                    request, fallback_policy.primary_model, policy.max_retries + 1,
                    "API_ERROR", used_fallback=True,
                )
                raise
            self._record(
                request, fallback_policy.primary_model, policy.max_retries + 1,
                result.failure_type, used_fallback=True,
            )
            return result

        # No fallback configured: surface the hard error so the call site can
        # degrade gracefully (every gateway.run() call site guards InferenceError).
        if primary_error is not None:
            raise primary_error
        return result

    def _record(self, request, model, attempt, failure_type, used_fallback):
        if self.telemetry is None:
            return
        self.telemetry.record(
            agent_name=request.agent_name,
            model=model,
            attempt=attempt,
            failure_type=failure_type,
            used_fallback=used_fallback,
        )
