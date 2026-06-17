from types import SimpleNamespace

from services.inference.models import InferencePolicy, InferenceRequest
from services.inference.providers.gemini_provider import GeminiProvider
from services.inference.providers.key_pool import GeminiKeyPool


def _request():
    return InferenceRequest(
        agent_name="reasoning_agent", task_type="t",
        system_prompt="sys", user_prompt="usr", output_mode="json",
    )


def _policy():
    return InferencePolicy(agent_name="reasoning_agent", primary_model="gemini-2.5-flash-lite")


def _provider(response):
    class _Models:
        def generate_content(self, **kwargs):
            return response

    class _Client:
        models = _Models()

    pool = GeminiKeyPool(["k"], client_factory=lambda k: _Client())
    return GeminiProvider(pool=pool)


def test_usage_metadata_is_surfaced_into_result():
    response = SimpleNamespace(
        text='{"ok": true}',
        usage_metadata=SimpleNamespace(
            prompt_token_count=10, candidates_token_count=5, total_token_count=15
        ),
    )
    result = _provider(response).generate(_request(), _policy())
    assert result.usage == {"input": 10, "output": 5, "total": 15}


def test_missing_usage_metadata_yields_none():
    response = SimpleNamespace(text='{"ok": true}')  # no usage_metadata attr
    result = _provider(response).generate(_request(), _policy())
    assert result.usage is None
