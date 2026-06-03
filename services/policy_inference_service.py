import json

from services.inference.models import InferenceError, InferenceRequest


POLICY_SYSTEM_PROMPT = """
Interpret only ambiguous policy text or conflicting evidence.
Return JSON with keys: warnings and requires_human_verification.
Never promise admission certainty.
"""


def interpret_policy_ambiguity(user_query: str, conflicts, gateway):
    default = {"warnings": [], "requires_human_verification": False}
    if hasattr(gateway, "is_available") and not gateway.is_available():
        return default

    payload = {"user_query": user_query, "conflicts": conflicts}
    try:
        result = gateway.run(
            InferenceRequest(
                agent_name="policy_agent",
                task_type="policy_ambiguity",
                system_prompt=POLICY_SYSTEM_PROMPT.strip(),
                user_prompt=json.dumps(payload, ensure_ascii=False),
                output_mode="json",
                temperature=0.0,
            )
        )
    except InferenceError:
        return default
    return result.parsed_data or default