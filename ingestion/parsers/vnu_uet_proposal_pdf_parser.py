"""
VNU-UET proposal PDF parser.

The proposal PDF's main quota table (section "4. Tổng số lượng tuyển sinh")
contains one row per program, formatted by pdfplumber as a single line:

    <row_num>. <code> <name> <mã ngành> <nhóm ngành> <quota>

The mã ngành is a 7-character alphanumeric token (e.g. 7480201, 75290A1) and
the quota is the first 2-4 digit number that follows it. Anchoring on this
shape lets us assign each quota to its own row without depending on the order
in which pdfminer would emit column cells (the previous parser had to
hard-code a swap for CN12/CN13 because of that fragility).
"""

import io
import logging
import re
from typing import List, Optional

from ingestion.config.settings import ADMISSION_YEAR
from ingestion.models.pipeline_models import ExtractedAdmissionFact, SourceReference
from ingestion.parsers.base_parser import BaseSpecializedParser

logger = logging.getLogger(__name__)

_SOURCE_ID = "vnuhn_proposal_pdf_2026"
_METHOD_RAW = "Xét tuyển tài năng"
_SUBJECT_COMBINATIONS = ["A00", "A01", "X06", "A02"]

_SECTION_START = "Tổng số lượng tuyển sinh"
# The program table is closed by the "(-) * Chương trình đào tạo thí điểm." footnote.
_RE_SECTION_END = re.compile(r"\n\(-\)\s*\*")

_RE_ROW = re.compile(
    r"^\s*(?P<row_num>\d+)\.\s*"
    r"(?P<code>CN\d+)\s+"
    r"(?P<name_raw>.+?)\s+"
    r"(?P<ma_nganh>\d[\dA-Z]{6})\b"
    r"(?P<after>.*)$"
)
_RE_QUOTA_VALUE = re.compile(r"\b(\d{2,4})\b")


def _extract_pdf_text(content: bytes) -> str:
    """Extract text from a PDF with pdfplumber, preserving row layout."""
    import pdfplumber

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def _slice_program_section(text: str) -> Optional[str]:
    idx = text.find(_SECTION_START)
    if idx < 0:
        return None
    section = text[idx:]
    end = _RE_SECTION_END.search(section)
    if end:
        section = section[: end.start()]
    return section


def _augment_name_with_prev_line(name_raw: str, prev_line: str) -> str:
    name = name_raw.strip()
    # When pdfplumber wraps a long program name, the row line begins with the
    # parenthetical continuation while the bare program name sits on the line
    # above. Prepending that line lets the canonical mapper substring-match.
    if name.startswith("(") and prev_line and not _RE_ROW.match(prev_line):
        return f"{prev_line.strip()} {name}"
    return name


class VnuUetProposalPdfParser(BaseSpecializedParser):
    """Specialized parser for the VNU-UET 2026 proposal PDF."""

    parser_profile = "vnu_uet_proposal_pdf"

    def parse(
        self,
        content: bytes,
        source_url: str,
        school_id: str = "vnu_uet",
        school_name: str = "Truong Dai hoc Cong nghe - DHQGHN",
        source_metadata: Optional[dict] = None,
    ) -> List[ExtractedAdmissionFact]:
        text = _extract_pdf_text(content)
        facts = self._facts_from_text(text, source_url, school_id, school_name)
        logger.info(
            "VnuUetProposalPdfParser: extracted %s facts from main quota table",
            len(facts),
        )
        return facts

    def _facts_from_text(
        self,
        text: str,
        source_url: str,
        school_id: str,
        school_name: str,
    ) -> List[ExtractedAdmissionFact]:
        section = _slice_program_section(text)
        if section is None:
            logger.warning(
                "VnuUetProposalPdfParser: section %r not found in PDF text",
                _SECTION_START,
            )
            return []

        facts: List[ExtractedAdmissionFact] = []
        lines = section.splitlines()
        for idx, line in enumerate(lines):
            match = _RE_ROW.match(line)
            if not match:
                continue
            quota_match = _RE_QUOTA_VALUE.search(match.group("after"))
            if not quota_match:
                logger.debug(
                    "VnuUetProposalPdfParser: no quota after mã ngành on row %r",
                    line,
                )
                continue

            prev_line = lines[idx - 1] if idx > 0 else ""
            program_name = _augment_name_with_prev_line(
                match.group("name_raw"), prev_line
            )

            facts.append(
                ExtractedAdmissionFact(
                    school_name=school_name,
                    admission_year=ADMISSION_YEAR,
                    program_name=program_name,
                    program_code=match.group("code"),
                    admission_method_raw=_METHOD_RAW,
                    subject_combinations_raw=_SUBJECT_COMBINATIONS,
                    quota_raw=quota_match.group(1),
                    source_reference=SourceReference(
                        source_id=_SOURCE_ID,
                        source_url=source_url,
                        school_id=school_id,
                        trust_level=5,
                    ),
                    confidence_score=0.88,
                    extraction_method="vnu_uet_proposal_pdf_row_anchored",
                )
            )

        return facts
