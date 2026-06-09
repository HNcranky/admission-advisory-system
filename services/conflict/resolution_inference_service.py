import json

from services.inference.models import InferenceError, InferenceRequest

RESOLUTION_SYSTEM_PROMPT = """
You are resolving a conflict between admission-data sources for the same program field.
Choose the single most trustworthy source. Prefer higher trust_level, more recent
fetched_at, and higher confidence_score. Never invent a value.
Return JSON with exactly these keys:
- confidence: "high" or "low"
- chosen_source_url: the source_url of the option you trust most
- rationale: one short Vietnamese sentence explaining the choice
Use "high" only when one source is clearly more trustworthy than the others.
""".strip()


def _serialize_option(option):
    return {
        "source_url": option.source_url,
        "trust_level": option.trust_level,
        "fetched_at": option.fetched_at.isoformat() if option.fetched_at else None,
        "confidence_score": option.confidence_score,
        "value": option.value,
    }


def interpret_conflict_tiebreak(record, report, gateway) -> dict:
    default = {"confidence": "low"}
    if hasattr(gateway, "is_available") and not gateway.is_available():
        return default

    payload = {
        "field_name": record.field_name,
        "school_name": record.school_name,
        "program_name": record.program_name,
        "admission_year": record.admission_year,
        "options": [_serialize_option(option) for option in report.ranked_options],
    }
    try:
        result = gateway.run(
            InferenceRequest(
                agent_name="resolution_agent",
                task_type="conflict_tiebreak",
                system_prompt=RESOLUTION_SYSTEM_PROMPT,
                user_prompt=json.dumps(payload, ensure_ascii=False, default=str),
                output_mode="json",
                temperature=0.0,
            )
        )
    except InferenceError:
        return default
    return result.parsed_data or default


BATCH_RESOLUTION_SYSTEM_PROMPT = """
You are resolving SEVERAL conflicts between admission-data sources, each for one
program field. For EACH conflict choose the single most trustworthy source.
Prefer higher trust_level, more recent fetched_at, and higher confidence_score.
Never invent a value.
Return JSON: {"decisions": [ ... ]} with one entry per conflict, each entry:
- conflict_key: echo back exactly the conflict_key given for that conflict
- confidence: "high" or "low"
- chosen_source_url: the source_url of the option you trust most
- rationale: one short Vietnamese sentence explaining the choice
Use "high" only when one source is clearly more trustworthy than the others.
""".strip()


def batch_interpret_conflict_tiebreak(pairs, gateway) -> dict:
    """pairs: list[(ConflictRecord, ComparisonReport)] needing a tiebreak.

    One LLM call for the whole batch. Returns {conflict_key: decision_dict}.
    Degrades to {} (gateway unavailable / InferenceError / empty) so every caller
    treats a missing conflict_key as low-confidence (== unresolved).
    """
    if not pairs:
        return {}
    if hasattr(gateway, "is_available") and not gateway.is_available():
        return {}

    payload = {
        "conflicts": [
            {
                "conflict_key": record.conflict_key,
                "field_name": record.field_name,
                "school_name": record.school_name,
                "program_name": record.program_name,
                "admission_year": record.admission_year,
                "options": [_serialize_option(option) for option in report.ranked_options],
            }
            for record, report in pairs
        ]
    }
    try:
        result = gateway.run(
            InferenceRequest(
                agent_name="resolution_agent",
                task_type="conflict_tiebreak_batch",
                system_prompt=BATCH_RESOLUTION_SYSTEM_PROMPT,
                user_prompt=json.dumps(payload, ensure_ascii=False, default=str),
                output_mode="json",
                temperature=0.0,
            )
        )
    except InferenceError:
        return {}

    data = result.parsed_data or {}
    decisions = {}
    for entry in data.get("decisions", []) or []:
        if isinstance(entry, dict) and entry.get("conflict_key"):
            decisions[str(entry["conflict_key"])] = entry
    return decisions
