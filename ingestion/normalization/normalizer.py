import logging
import json
from typing import List, Optional

from ingestion.models.pipeline_models import (
    ExtractedAdmissionFact,
    NormalizedAdmissionRecord,
)
from ingestion.normalization.program_mapper import map_program
from ingestion.normalization.method_mapper import map_method
from ingestion.normalization.subject_combination_mapper import map_combinations
from ingestion.normalization.quota_parser import parse_quota
from ingestion.normalization.combo_method_mapper import (
    infer_methods_from_combos,
    get_method_display_name,
)

logger = logging.getLogger(__name__)


def normalize_fact(
    fact: ExtractedAdmissionFact,
    school_id: str = "",
) -> NormalizedAdmissionRecord:
    """
    Normalize a single extracted fact into a canonical record.

    Args:
        fact: Raw extracted admission fact
        school_id: School identifier for school-specific normalization

    Returns:
        Normalized admission record
    """
                                                            
    if not school_id:
        school_id = fact.source_reference.school_id



    program_id, program_canonical = map_program(
        fact.program_name, fact.program_code, school_id=school_id
    )


                                                           
    method = None
    if fact.admission_method_raw:
                                                                      
        mapped = map_method(fact.admission_method_raw, school_id=school_id)
        if mapped:
            method_parts = [m.strip() for m in mapped.split(";") if m.strip()]
            method_names = [
                get_method_display_name(code, school_id=school_id)
                for code in method_parts
            ]
            method = "; ".join(method_names) if method_names else None
    else:
                                                                   
        inferred_codes = infer_methods_from_combos(
            combos=fact.subject_combinations_raw,
            school_id=school_id,
        )
        if inferred_codes:
                                                   
            method_names = [
                get_method_display_name(code, school_id=school_id)
                for code in inferred_codes
            ]
            method = "; ".join(method_names)

                              
    combos = map_combinations(fact.subject_combinations_raw)

                 
    quota = parse_quota(fact.quota_raw)

    conditions_payload = None
    if fact.additional_conditions_raw:
        try:
            conditions_payload = json.loads(fact.additional_conditions_raw)
        except (TypeError, json.JSONDecodeError):
            conditions_payload = {"raw": fact.additional_conditions_raw}

    record = NormalizedAdmissionRecord(
        school_id=school_id,
        school_name_canonical=fact.school_name,
        admission_year=fact.admission_year,
        program_id=program_id,
        program_name_canonical=program_canonical,
        program_name_raw=fact.program_name,
        admission_method=method,
        admission_method_raw=fact.admission_method_raw,
        subject_combinations=combos,
        quota=quota,
        metadata=conditions_payload,
        tuition=(
            {"raw": fact.tuition_raw}
            if fact.tuition_raw else None
        ),
        source_url=fact.source_reference.source_url,
        source_trust_level=fact.source_reference.trust_level,
        confidence_score=fact.confidence_score,
    )

    return record


def normalize_facts(
    facts: List[ExtractedAdmissionFact],
    school_id: str = "",
) -> List[NormalizedAdmissionRecord]:
    """
    Normalize a batch of facts.

    Args:
        facts: List of raw extracted facts
        school_id: School identifier (optional, derived from facts if empty)

    Returns:
        List of normalized records
    """
    records = []
    for fact in facts:
        try:
            record = normalize_fact(fact, school_id=school_id)
            records.append(record)
        except Exception as e:
            logger.error(
                f"Failed to normalize fact for "
                f"'{fact.program_name}': {e}"
            )

    logger.info(f"Normalized {len(records)}/{len(facts)} facts")
    return records
