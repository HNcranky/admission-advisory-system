                                
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
from datetime import datetime

from ingestion.storage.db_connection import get_cursor
from ingestion.models.pipeline_models import (
    FetchResult,
    DocumentType,
    ParsedContent,
    ExtractedAdmissionFact,
    NormalizedAdmissionRecord,
)

logger = logging.getLogger(__name__)


                                                                  

def save_raw_document(
    fetch_result: FetchResult,
    source_id: str,
    doc_type: DocumentType,
    parsed: Optional[ParsedContent] = None,
) -> Optional[int]:
    """
    Save a fetched document to the raw_documents table.

    Returns:
        The inserted document ID, or None on failure
    """
    try:
        with get_cursor() as cur:
            cur.execute("""
                INSERT INTO raw_documents
                    (url, final_url, source_id, content_type, http_status,
                     content_hash, raw_content, headers, fetched_at,
                     document_type, parsed_text, parsed_structure)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                fetch_result.url,
                fetch_result.final_url,
                source_id,
                fetch_result.content_type,
                fetch_result.http_status,
                fetch_result.content_hash,
                psycopg2_Binary(fetch_result.raw_content),
                json.dumps(fetch_result.headers),
                fetch_result.fetched_at,
                doc_type.value,
                parsed.text if parsed else None,
                json.dumps(parsed.model_dump(mode="json"), ensure_ascii=False)
                if parsed else None,
            ))
            doc_id = cur.fetchone()[0]
            logger.info(f"Saved raw document id={doc_id} for {fetch_result.url}")
            return doc_id
    except Exception as e:
        logger.error(f"Failed to save raw document: {e}")
        return None


def psycopg2_Binary(data: bytes):
    """Wrap bytes for psycopg2 BYTEA insertion."""
    import psycopg2
    return psycopg2.Binary(data)


                                                                  

def save_extracted_facts(
    facts: List[ExtractedAdmissionFact],
    raw_document_id: Optional[int] = None,
) -> List[int]:
    """
    Save extracted facts to the extracted_facts table.

    Returns:
        List of inserted fact IDs
    """
    ids = []
    try:
        with get_cursor() as cur:
            for fact in facts:
                cur.execute("""
                    INSERT INTO extracted_facts
                        (raw_document_id, school_name, admission_year,
                         program_name, program_code, admission_method_raw,
                         subject_combinations_raw, quota_raw, deadline_raw,
                         additional_conditions_raw, tuition_raw,
                         confidence_score, extraction_method)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    raw_document_id,
                    fact.school_name,
                    fact.admission_year,
                    fact.program_name,
                    fact.program_code,
                    fact.admission_method_raw,
                    json.dumps(fact.subject_combinations_raw)
                    if fact.subject_combinations_raw else None,
                    fact.quota_raw,
                    fact.deadline_raw,
                    fact.additional_conditions_raw,
                    fact.tuition_raw,
                    fact.confidence_score,
                    fact.extraction_method,
                ))
                fact_id = cur.fetchone()[0]
                ids.append(fact_id)

        logger.info(f"Saved {len(ids)} extracted facts")
    except Exception as e:
        logger.error(f"Failed to save extracted facts: {e}")

    return ids


                                                                  

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


                                                                  

def load_and_save_from_json(json_path: str) -> int:
    """
    Load normalized records from a JSON file and save to DB.
    Useful for importing previously generated pipeline output.

    Args:
        json_path: Path to JSON file with normalized records

    Returns:
        Number of records saved
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    records = []
    for item in data:
        record = NormalizedAdmissionRecord(**item)
        records.append(record)

    logger.info(f"Loaded {len(records)} records from {json_path}")
    return save_canonical_records(records)
