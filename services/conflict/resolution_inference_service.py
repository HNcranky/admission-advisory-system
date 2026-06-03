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
