import re
import logging
from typing import List

from ingestion.models.pipeline_models import (
    ParsedContent,
    ExtractedAdmissionFact,
    SourceReference,
)
from ingestion.config.settings import ADMISSION_YEAR

logger = logging.getLogger(__name__)


def extract_admission_facts(
    parsed: ParsedContent,
    source_ref: SourceReference,
    school_name: str = "Unknown",
    use_llm_fallback: bool = True,
) -> List[ExtractedAdmissionFact]:
    """
    Extract admission facts from parsed content.

    Args:
        parsed: Structured parsed content
        source_ref: Source reference for traceability
        school_name: School name (from source registry, not detected)
        use_llm_fallback: Whether to use LLM if regex confidence is low

    Returns:
        List of extracted facts
    """
                                                                  
    regex_facts = _regex_extract(parsed, source_ref, school_name)

    logger.info(
        f"Regex extraction: {len(regex_facts)} facts, "
        f"avg confidence: {_avg_confidence(regex_facts):.2f}"
    )

                                                                  
    if use_llm_fallback and (
        not regex_facts or _avg_confidence(regex_facts) < 0.6
    ):
        logger.info("Confidence low, attempting LLM extraction...")
        try:
            from ingestion.extractors.llm_extractor import llm_extract
            llm_facts = llm_extract(parsed, source_ref, school_name)

            if llm_facts:
                                                                    
                if len(llm_facts) > len(regex_facts):
                    logger.info(
                        f"Using LLM results ({len(llm_facts)} facts) "
                        f"over regex ({len(regex_facts)} facts)"
                    )
                    return llm_facts
                else:
                                                  
                    return _merge_facts(regex_facts, llm_facts)
        except Exception as e:
            logger.warning(f"LLM extraction failed: {e}")

    return regex_facts


def _regex_extract(
    parsed: ParsedContent,
    source_ref: SourceReference,
    school_name: str,
) -> List[ExtractedAdmissionFact]:
    """Regex-based extraction from parsed text."""
    text = parsed.text
    facts = []

                                                                        
    detected_school = school_name

                                                                 
    patterns = [
                                    
        r"([A-ZĐa-zÀ-ỹ\s]+)\((\w+)\).*?(\d+)\s*chỉ tiêu",
                                         
        r"Ngành\s+(.*?)\s*Mã\s+(\w+)\s*Chỉ tiêu\s*(\d+)",
                                        
        r"Ngành\s+(.*?)\s*tuyển\s+(\d+)\s*chỉ tiêu",
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for m in matches:
            program_name = m[0].strip() if len(m) > 0 else None
            program_code = None
            quota_raw = None

            if len(m) == 3 and m[2].isdigit():
                quota_raw = m[2]
                if not m[1].isdigit():
                    program_code = m[1]

            facts.append(ExtractedAdmissionFact(
                school_name=detected_school,
                admission_year=ADMISSION_YEAR,
                program_name=program_name,
                program_code=program_code,
                quota_raw=quota_raw,
                subject_combinations_raw=_extract_combos_near(text, program_name),
                source_reference=source_ref,
                confidence_score=0.6,
                extraction_method="regex",
            ))

                                                                  
    for table in parsed.tables:
        table_facts = _extract_from_table(
            table, detected_school, source_ref
        )
        facts.extend(table_facts)

    return facts


def _extract_combos_near(
    text: str, program_name: str
) -> List[str]:
    """Extract subject combinations near a program mention."""
    combo_pattern = r"\b([A-Z]{1,2}\d{2})\b"
    if program_name:
                                                                
        idx = text.lower().find(program_name.lower())
        if idx >= 0:
            vicinity = text[max(0, idx-100):idx+500]
            return list(set(re.findall(combo_pattern, vicinity)))

    return list(set(re.findall(combo_pattern, text)))


def _extract_from_table(
    table: List[List[str]],
    school_name: str,
    source_ref: SourceReference,
) -> List[ExtractedAdmissionFact]:
    """Extract facts from a table structure."""
    facts = []
    if not table or len(table) < 2:
        return facts

                             
    header = [h.lower() for h in table[0]]
    col_map = _identify_columns(header)

    if not col_map:
        return facts

    for row in table[1:]:
        if len(row) < len(header):
            continue

        fact_data = {}
        for field, col_idx in col_map.items():
            if col_idx < len(row):
                fact_data[field] = row[col_idx]

        if fact_data.get("program_name"):
            combos = []
            if fact_data.get("subject_combinations"):
                combos = re.findall(
                    r"[A-Z]{1,2}\d{2}",
                    fact_data["subject_combinations"]
                )

            facts.append(ExtractedAdmissionFact(
                school_name=school_name,
                admission_year=ADMISSION_YEAR,
                program_name=fact_data.get("program_name"),
                program_code=fact_data.get("program_code"),
                quota_raw=fact_data.get("quota"),
                subject_combinations_raw=combos if combos else None,
                source_reference=source_ref,
                confidence_score=0.7,
                extraction_method="table",
            ))

    return facts


def _identify_columns(header: List[str]) -> dict:
    """Try to map header names to known fields."""
    col_map = {}
    keywords = {
        "program_name": ["ngành", "chương trình", "tên ngành", "program"],
        "program_code": ["mã", "code", "mã ngành", "mã xét tuyển"],
        "quota": ["chỉ tiêu", "quota", "số lượng"],
        "subject_combinations": ["tổ hợp", "môn", "combination"],
    }

    for field, kws in keywords.items():
        for i, h in enumerate(header):
            if any(kw in h for kw in kws):
                col_map[field] = i
                break

    return col_map


def _merge_facts(
    regex_facts: List[ExtractedAdmissionFact],
    llm_facts: List[ExtractedAdmissionFact],
) -> List[ExtractedAdmissionFact]:
    """Merge regex and LLM facts, preferring LLM where overlap exists."""
    llm_codes = {f.program_code for f in llm_facts if f.program_code}
    merged = list(llm_facts)

    for rf in regex_facts:
        if rf.program_code and rf.program_code not in llm_codes:
            merged.append(rf)

    return merged


def _avg_confidence(facts: List[ExtractedAdmissionFact]) -> float:
    """Average confidence score of a list of facts."""
    if not facts:
        return 0.0
    return sum(f.confidence_score for f in facts) / len(facts)