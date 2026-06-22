
"""
Storage layer: writes pipeline output to PostgreSQL.

Handles:
- raw_documents: raw fetched content
- extracted_facts: extracted admission facts (pre-normalization)
- canonical_admission_records: final normalized records
"""

import json
import logging
from typing import List, Optional

from ingestion.storage.db_connection import get_cursor
from ingestion.models.pipeline_models import (
    ExtractedAdmissionFact,
    NormalizedAdmissionRecord,
    NormalizedCutoffRecord,
)

logger = logging.getLogger(__name__)




def save_canonical_records(
    records: List[NormalizedAdmissionRecord],
    fact_ids: Optional[List[int]] = None,
) -> int:
    """
    Save normalized records to canonical_admission_records.
    Uses UPSERT (ON CONFLICT UPDATE) to handle duplicates.

    Returns:
        Number of records saved/updated
    """
    count = 0
    try:
        with get_cursor() as cur:
            for i, record in enumerate(records):
                fact_id = fact_ids[i] if fact_ids and i < len(fact_ids) else None


                combos_json = json.dumps(
                    [c.model_dump() for c in record.subject_combinations],
                    ensure_ascii=False
                ) if record.subject_combinations else None

                quota_json = json.dumps(
                    record.quota.model_dump(), ensure_ascii=False
                ) if record.quota else None

                deadline_json = json.dumps(
                    record.deadline.model_dump(), ensure_ascii=False
                ) if record.deadline else None

                metadata_json = json.dumps(
                    record.metadata, ensure_ascii=False
                ) if record.metadata else None

                tuition_json = json.dumps(
                    record.tuition, ensure_ascii=False
                ) if record.tuition else None

                cur.execute("""
                    INSERT INTO canonical_admission_records
                        (extracted_fact_id, school_id, school_name_canonical,
                         admission_year, program_id, program_name_canonical,
                         program_name_raw, admission_method, admission_method_raw,
                         subject_combinations, quota, deadline, metadata,
                         tuition, source_url, source_trust_level,
                         confidence_score)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (school_id, admission_year, program_id, admission_method, source_url)
                    DO UPDATE SET
                        program_name_canonical = EXCLUDED.program_name_canonical,
                        program_name_raw = EXCLUDED.program_name_raw,
                        admission_method_raw = EXCLUDED.admission_method_raw,
                        subject_combinations = EXCLUDED.subject_combinations,
                        quota = EXCLUDED.quota,
                        deadline = EXCLUDED.deadline,
                        metadata = EXCLUDED.metadata,
                        tuition = EXCLUDED.tuition,
                        source_url = EXCLUDED.source_url,
                        source_trust_level = EXCLUDED.source_trust_level,
                        confidence_score = EXCLUDED.confidence_score,
                        normalized_at = NOW()
                """, (
                    fact_id,
                    record.school_id,
                    record.school_name_canonical,
                    record.admission_year,
                    record.program_id,
                    record.program_name_canonical,
                    record.program_name_raw,
                    record.admission_method,
                    record.admission_method_raw,
                    combos_json,
                    quota_json,
                    deadline_json,
                    metadata_json,
                    tuition_json,
                    record.source_url,
                    record.source_trust_level,
                    record.confidence_score,
                ))
                count += 1

        logger.info(f"Saved {count} canonical records (upsert)")
    except Exception as e:
        logger.error(f"Failed to save canonical records: {e}")

    return count




def save_cutoff_records(records: List[NormalizedCutoffRecord]) -> int:
    """Upsert điểm chuẩn lịch sử vào cutoff_records (per-source, mirror migration 016).

    Trả số record đã ghi; lỗi DB → log + trả 0 (caller CLI so count để exit code).
    """
    count = 0
    try:
        with get_cursor() as cur:
            for record in records:
                combos_json = (
                    json.dumps(record.subject_combinations, ensure_ascii=False)
                    if record.subject_combinations else None
                )
                cur.execute("""
                    INSERT INTO cutoff_records
                        (school_id, program_id, program_name_canonical, program_name_raw,
                         cutoff_year, admission_method, score_scale, cutoff_score,
                         subject_combinations, note, source_url,
                         source_trust_level, confidence_score)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (school_id, cutoff_year, program_id, admission_method, source_url)
                    DO UPDATE SET
                        program_name_canonical = EXCLUDED.program_name_canonical,
                        program_name_raw = EXCLUDED.program_name_raw,
                        score_scale = EXCLUDED.score_scale,
                        cutoff_score = EXCLUDED.cutoff_score,
                        subject_combinations = EXCLUDED.subject_combinations,
                        note = EXCLUDED.note,
                        source_trust_level = EXCLUDED.source_trust_level,
                        confidence_score = EXCLUDED.confidence_score,
                        ingested_at = NOW()
                """, (
                    record.school_id,
                    record.program_id,
                    record.program_name_canonical,
                    record.program_name_raw,
                    record.cutoff_year,
                    record.admission_method,
                    record.score_scale,
                    record.cutoff_score,
                    combos_json,
                    record.note,
                    record.source_url,
                    record.source_trust_level,
                    record.confidence_score,
                ))
                count += 1
        logger.info(f"Saved {count} cutoff records (upsert)")
    except Exception as e:
        logger.error(f"Failed to save cutoff records: {e}")
        return 0
    return count
