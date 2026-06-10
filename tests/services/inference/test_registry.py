from services.inference.registry import ModelRegistry


def test_registry_resolves_default_and_agent_override():
    registry = ModelRegistry(
        default_model="gemini-2.5-flash-lite",
        agent_overrides={
            "reasoning_agent": {
                "primary_model": "gemini-2.5-flash-lite",
                "fallback_model": "gemini-2.5-flash",
                "allow_fallback": True,
                "output_mode": "json",
            }
        },
    )

    profile_policy = registry.resolve("profile_agent")
    reasoning_policy = registry.resolve("reasoning_agent")

    assert profile_policy.agent_name == "profile_agent"
    assert profile_policy.primary_model == "gemini-2.5-flash-lite"
    assert profile_policy.allow_fallback is False
    assert reasoning_policy.fallback_model == "gemini-2.5-flash"
    assert reasoning_policy.allow_fallback is True
    assert reasoning_policy.output_mode == "json"


def test_resolve_reads_max_tokens_from_override():
    registry = ModelRegistry(default_model="m", agent_overrides={"a": {"max_tokens": 512}})
    assert registry.resolve("a").max_tokens == 512


def test_resolve_max_tokens_defaults_to_none():
    registry = ModelRegistry(default_model="m")
    assert registry.resolve("a").max_tokens is None