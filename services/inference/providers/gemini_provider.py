import json

from google.genai import types

from services.inference.models import InferenceResult
from services.inference.providers.key_pool import GeminiKeyPool, get_key_pool


class GeminiProvider:
    provider_name = "gemini"

    def __init__(self, api_key: str | None = None, *, pool=None, client_factory=None):
        if pool is not None:
            self._pool = pool
        elif api_key is not None:
            kwargs = {"client_factory": client_factory} if client_factory else {}
            self._pool = GeminiKeyPool([api_key], **kwargs)
        else:
            self._pool = get_key_pool()

    def is_available(self) -> bool:
        return self._pool.has_keys()

    def generate(self, request, policy):
        # Key rotation (429/auth/5xx → next key; exhausted → InferenceError) is
        # handled uniformly by the shared pool loop.
        context = (
            f" for agent={request.agent_name} model={policy.primary_model}"
        )
        response = self._pool.call(
            lambda client: self._call(client, request, policy),
            context=context,
        )
        return self._build_result(response, request, policy)

    @staticmethod
    def _call(client, request, policy):
        json_mode = request.output_mode == "json"
        return client.models.generate_content(
            model=policy.primary_model,
            contents=request.user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=request.system_prompt,
                temperature=request.temperature,
                response_mime_type="application/json" if json_mode else None,
            ),
        )

    def _build_result(self, response, request, policy):
        text = (getattr(response, "text", "") or "").strip()

        def _result(**kwargs):
            return InferenceResult(
                agent_name=request.agent_name,
                model=policy.primary_model,
                provider=self.provider_name,
                content=text,
                **kwargs,
            )

        if request.output_mode != "json":
            return _result()
        if not text:
            return _result(failure_type="STRUCTURE_FAILURE")
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return _result(failure_type="STRUCTURE_FAILURE")
        return _result(parsed_data=parsed)
