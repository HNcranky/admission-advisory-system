# extractors/llm_extractor.py
"""
LLM-based schema-driven extraction, routed through the inference gateway.

All LLM calls go through ``build_default_gateway().run(...)`` so they get key
rotation, telemetry and fallback (audit §2.1). Degrades to an empty list on a
gateway failure or unparseable JSON, logging a warning so outages aren't silent.
"""

import logging
from typing import Any, Dict, List, Optional

from ingestion.config.settings import (
    ADMISSION_YEAR,
    LLM_MAX_CHUNK_SIZE,
)
from ingestion.models.pipeline_models import (
    ExtractedAdmissionFact,
    SourceReference,
    ParsedContent,
)
from services.inference.factory import build_default_gateway
from services.inference.models import InferenceError, InferenceRequest

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """Bạn là chuyên gia trích xuất thông tin tuyển sinh đại học Việt Nam.

Từ đoạn văn bản người dùng cung cấp, hãy trích xuất TẤT CẢ thông tin tuyển sinh theo schema JSON sau.
Mỗi ngành/chương trình là một object riêng trong mảng "facts".

Schema:
```json
{{
  "facts": [
    {{
      "school_name": "Tên trường (string)",
      "admission_year": {year},
      "program_name": "Tên ngành/chương trình (string hoặc null)",
      "program_code": "Mã ngành/mã xét tuyển (string hoặc null)",
      "admission_method_raw": "Phương thức tuyển sinh nguyên văn (string hoặc null)",
      "subject_combinations_raw": ["Danh sách tổ hợp môn", "ví dụ: A00, A01"],
      "quota_raw": "Chỉ tiêu nguyên văn (string hoặc null)",
      "deadline_raw": "Thời hạn/deadline nguyên văn (string hoặc null)",
      "additional_conditions_raw": "Điều kiện phụ nguyên văn (string hoặc null)",
      "tuition_raw": "Học phí nguyên văn (string hoặc null)"
    }}
  ]
}}
```

Quy tắc:
- Giữ nguyên văn bản gốc cho các trường _raw
- Nếu không tìm thấy thông tin, đặt null
- Một tài liệu có thể chứa nhiều ngành, trích xuất TẤT CẢ
- admission_year mặc định là {year} nếu không rõ
- Trả về ĐÚNG format JSON object có khóa "facts", không thêm text giải thích
""".format(year=ADMISSION_YEAR)

_USER_PROMPT = """VĂN BẢN:
{text}
"""


def llm_extract(
    parsed: ParsedContent,
    source_ref: SourceReference,
    school_name: str = "Unknown",
    *,
    gateway=None,
) -> List[ExtractedAdmissionFact]:
    """
    Use the inference gateway to extract structured admission facts.

    Args:
        parsed: Parsed content from a document
        source_ref: Reference to the source
        school_name: Default school name if not detected
        gateway: Optional injected gateway (FakeGateway in tests)

    Returns:
        List of extracted admission facts (empty on any failure — degrade graceful).
    """
    text = parsed.text
    if not text or len(text.strip()) < 50:
        logger.warning("Text too short for LLM extraction")
        return []

    gw = gateway or build_default_gateway()
    chunks = _chunk_text(text, LLM_MAX_CHUNK_SIZE)
    all_facts: List[ExtractedAdmissionFact] = []

    for i, chunk in enumerate(chunks):
        try:
            result = gw.run(
                InferenceRequest(
                    agent_name="fact_extractor",
                    task_type="admission_fact_extraction",
                    system_prompt=_SYSTEM_PROMPT,
                    user_prompt=_USER_PROMPT.format(text=chunk),
                    output_mode="json",
                    temperature=0.1,
                )
            )
        except InferenceError as exc:
            # Gateway already retried/fell back; a hard failure here means degrade.
            logger.warning("llm_extract degraded (gateway failure) on chunk %d/%d: %s",
                           i + 1, len(chunks), exc)
            continue

        raw = result.parsed_data
        if not raw:
            # gateway returned STRUCTURE_FAILURE (no parseable JSON) → degrade.
            logger.warning("llm_extract got no parseable JSON for chunk %d/%d", i + 1, len(chunks))
            continue

        chunk_facts = _to_facts(raw, source_ref, school_name)
        all_facts.extend(chunk_facts)
        logger.info("LLM extracted %d facts from chunk %d/%d", len(chunk_facts), i + 1, len(chunks))

    return all_facts


def _to_facts(
    raw: Dict[str, Any], source_ref: SourceReference, school_name: str
) -> List[ExtractedAdmissionFact]:
    """Map the gateway JSON (``{"facts": [...]}``) to ExtractedAdmissionFact."""
    items = raw.get("facts", []) if isinstance(raw, dict) else (raw or [])
    facts: List[ExtractedAdmissionFact] = []
    for item in items:
        facts.append(
            ExtractedAdmissionFact(
                school_name=item.get("school_name", school_name),
                admission_year=item.get("admission_year", ADMISSION_YEAR),
                program_name=item.get("program_name"),
                program_code=item.get("program_code"),
                admission_method_raw=item.get("admission_method_raw"),
                subject_combinations_raw=item.get("subject_combinations_raw"),
                quota_raw=item.get("quota_raw"),
                deadline_raw=item.get("deadline_raw"),
                additional_conditions_raw=item.get("additional_conditions_raw"),
                tuition_raw=item.get("tuition_raw"),
                source_reference=source_ref,
                confidence_score=0.75,
                extraction_method="llm_gemini",
            )
        )
    return facts


def _chunk_text(text: str, max_size: int) -> List[str]:
    """Split text into chunks, trying to break at paragraph boundaries."""
    if len(text) <= max_size:
        return [text]

    chunks = []
    start = 0

    while start < len(text):
        end = start + max_size

        if end >= len(text):
            chunks.append(text[start:])
            break

        # Try to break at paragraph boundary
        break_pos = text.rfind("\n\n", start, end)
        if break_pos == -1 or break_pos <= start:
            # Try single newline
            break_pos = text.rfind("\n", start, end)
        if break_pos == -1 or break_pos <= start:
            break_pos = end

        chunks.append(text[start:break_pos])
        start = break_pos

    return chunks
