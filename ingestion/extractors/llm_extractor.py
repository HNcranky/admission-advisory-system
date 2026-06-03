# extractors/llm_extractor.py
"""
LLM-based schema-driven extraction using Gemini 2.5 Flash.

Uses structured output to extract admission facts from parsed text.
Fallback: returns empty list if LLM call fails.
"""

import json
import logging
from typing import List, Optional

from ingestion.config.settings import (
    GEMINI_API_KEY,
    GEMINI_EXTRACTION_MODEL,
    ADMISSION_YEAR,
    LLM_MAX_CHUNK_SIZE,
)
from ingestion.models.pipeline_models import (
    ExtractedAdmissionFact,
    SourceReference,
    ParsedContent,
)

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """Bạn là chuyên gia trích xuất thông tin tuyển sinh đại học Việt Nam.

Từ đoạn văn bản dưới đây, hãy trích xuất TẤT CẢ thông tin tuyển sinh theo schema JSON sau.
Mỗi ngành/chương trình là một object riêng trong mảng.

Schema:
```json
[
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
```

Quy tắc:
- Giữ nguyên văn bản gốc cho các trường _raw
- Nếu không tìm thấy thông tin, đặt null
- Một tài liệu có thể chứa nhiều ngành, trích xuất TẤT CẢ
- admission_year mặc định là {year} nếu không rõ
- Trả về ĐÚNG format JSON array, không thêm text giải thích

VĂN BẢN:
{text}
"""


def llm_extract(
    parsed: ParsedContent,
    source_ref: SourceReference,
    school_name: str = "Unknown",
) -> List[ExtractedAdmissionFact]:
    """
    Use Gemini to extract structured admission facts from parsed content.

    Args:
        parsed: Parsed content from a document
        source_ref: Reference to the source
        school_name: Default school name if not detected

    Returns:
        List of extracted admission facts
    """
    if not GEMINI_API_KEY:
        logger.warning(
            "GEMINI_API_KEY not set, skipping LLM extraction"
        )
        return []

    try:
        import google.generativeai as genai
    except ImportError:
        logger.error(
            "google-generativeai not installed. "
            "Run: pip install google-generativeai"
        )
        return []

    text = parsed.text
    if not text or len(text.strip()) < 50:
        logger.warning("Text too short for LLM extraction")
        return []

    # Chunk if too long
    chunks = _chunk_text(text, LLM_MAX_CHUNK_SIZE)
    all_facts: List[ExtractedAdmissionFact] = []

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(GEMINI_EXTRACTION_MODEL)

    for i, chunk in enumerate(chunks):
        prompt = EXTRACTION_PROMPT.format(
            year=ADMISSION_YEAR,
            text=chunk,
        )

        try:
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    max_output_tokens=8192,
                ),
            )

            response_text = response.text.strip()

            # Strip markdown code blocks if present
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1])

            raw_facts = json.loads(response_text)

            for raw in raw_facts:
                fact = ExtractedAdmissionFact(
                    school_name=raw.get("school_name", school_name),
                    admission_year=raw.get("admission_year", ADMISSION_YEAR),
                    program_name=raw.get("program_name"),
                    program_code=raw.get("program_code"),
                    admission_method_raw=raw.get("admission_method_raw"),
                    subject_combinations_raw=raw.get("subject_combinations_raw"),
                    quota_raw=raw.get("quota_raw"),
                    deadline_raw=raw.get("deadline_raw"),
                    additional_conditions_raw=raw.get("additional_conditions_raw"),
                    tuition_raw=raw.get("tuition_raw"),
                    source_reference=source_ref,
                    confidence_score=0.75,
                    extraction_method="llm_gemini",
                )
                all_facts.append(fact)

            logger.info(
                f"LLM extracted {len(raw_facts)} facts "
                f"from chunk {i+1}/{len(chunks)}"
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
        except Exception as e:
            logger.error(f"LLM extraction failed: {e}")

    return all_facts


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
