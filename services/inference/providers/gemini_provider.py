import json
import logging

from google.genai import types

from services.inference.models import InferenceResult
from services.inference.providers.key_pool import GeminiKeyPool, get_key_pool

logger = logging.getLogger(__name__)


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
        if request.media:
            # Vision call: image parts first, then the instruction text.
            contents = [
                types.Part.from_bytes(data=data, mime_type=mime)
                for mime, data in request.media
            ] + [request.user_prompt]
        else:
            contents = request.user_prompt

        config_kwargs = dict(
            system_instruction=request.system_prompt,
            temperature=request.temperature,
            response_mime_type="application/json" if json_mode else None,
            max_output_tokens=policy.max_tokens,
        )
        if policy.thinking_budget is not None:
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_budget=policy.thinking_budget
            )
        if json_mode and request.response_schema is not None:
            config_kwargs["response_schema"] = request.response_schema

        return client.models.generate_content(
            model=policy.primary_model,
            contents=contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )

    def _build_result(self, response, request, policy):
        text = (getattr(response, "text", "") or "").strip()
        usage = self._extract_usage(response)

        def _result(**kwargs):
            return InferenceResult(
                agent_name=request.agent_name,
                model=policy.primary_model,
                provider=self.provider_name,
                content=text,
                usage=usage,
                **kwargs,
            )

        def _structure_failure():
            # A truncated response (finish_reason=MAX_TOKENS) yields invalid/empty
            # JSON that looks identical to a model mistake but is really a token
            # budget too small for this agent. Surface it so it doesn't silently
            # degrade to "no data" across every retry (see knowledge_qa_agent).
            if self._is_truncated(response):
                out = (usage or {}).get("output")
                logger.warning(
                    "%s output truncated at max_tokens=%s (output_tokens=%s) → "
                    "STRUCTURE_FAILURE; raise the agent's max_tokens budget.",
                    request.agent_name, policy.max_tokens, out,
                )
            return _result(failure_type="STRUCTURE_FAILURE")

        if request.output_mode != "json":
            return _result()
        if not text:
            return _structure_failure()
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return _structure_failure()
        return _result(parsed_data=parsed)

    @staticmethod
    def _is_truncated(response) -> bool:
        try:
            reason = response.candidates[0].finish_reason
        except (AttributeError, IndexError, TypeError):
            return False
        return getattr(reason, "name", str(reason)) == "MAX_TOKENS"

    @staticmethod
    def _extract_usage(response):
        meta = getattr(response, "usage_metadata", None)
        if meta is None:
            return None

        def _count(name):
            value = getattr(meta, name, None)
            return int(value) if isinstance(value, (int, float)) else None

        return {
            "input": _count("prompt_token_count"),
            "output": _count("candidates_token_count"),
            "total": _count("total_token_count"),
        }
