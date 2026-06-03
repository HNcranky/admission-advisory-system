"""
HUST 2026 admission announcement HTML parser.

Source: https://ts.hust.edu.vn/tin-tuc/thong-tin-tuyen-sinh-dai-hoc-chinh-quy-nam-2026

The article body contains a single quota table with 78 rows. The header is
2 rows tall: row 0 spans the top columns
  TT | Chương trình/ngành đào tạo | Chỉ tiêu dự kiến | Mã xét tuyển | Phương thức tuyển sinh (colspan=3)
and row 1 contains the method sub-headers
  XTTN | ĐGTD | THPT
Data rows therefore have 7 cells: [TT, name, quota, code, XTTN_flag, ĐGTD_flag, THPT_flag].
Method columns contain the glyph 'Ö' to flag eligibility; they are NOT
numeric quotas. We emit one fact per program-row with the program-total
quota (column "Chỉ tiêu dự kiến"). Section divider rows
(e.g. "A. CHƯƠNG TRÌNH CHUẨN") have a single cell and are skipped, as is
the final "Tổng chỉ tiêu: 9.880" totals row whose first cell is non-numeric.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional

from bs4 import BeautifulSoup

from ingestion.parsers.base_parser import BaseSpecializedParser
from ingestion.models.pipeline_models import ExtractedAdmissionFact, SourceReference
from ingestion.config.settings import ADMISSION_YEAR

logger = logging.getLogger(__name__)

_NUMERIC_RE = re.compile(r"\d[\d.,]*")
_METHOD_FLAG_GLYPHS = {"Ö", "X", "x", "✓", "✔"}


def _is_method_flag_set(cell_text: str) -> bool:
    return bool(cell_text) and any(g in cell_text for g in _METHOD_FLAG_GLYPHS)


def _digits_only(text: str) -> Optional[str]:
    m = _NUMERIC_RE.search(text or "")
    if not m:
        return None
    return re.sub(r"[^\d]", "", m.group(0))


def _is_quota_table(table) -> bool:
    """Detect the quota table by its top-header row containing 'Chỉ tiêu' and 'ngành'."""
    rows = table.find_all("tr")
    if not rows:
        return False
    header_text = " ".join(c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"]))
    return "Chỉ tiêu" in header_text and "ngành" in header_text.lower()


class HustAnnouncementHtmlParser(BaseSpecializedParser):
    """Specialized parser for HUST's 2026 admission announcement article."""

    parser_profile = "hust_announcement_html"

    def parse(
        self,
        content: bytes,
        source_url: str,
        school_id: str = "hust",
        school_name: str = "Đại học Bách khoa Hà Nội",
        source_metadata: Optional[dict] = None,
    ) -> List[ExtractedAdmissionFact]:
        facts: list[ExtractedAdmissionFact] = []
        soup = BeautifulSoup(content, "html.parser")

        target_table = next(
            (t for t in soup.find_all("table") if _is_quota_table(t)),
            None,
        )
        if target_table is None:
            logger.warning(f"HustAnnouncementHtmlParser: quota table not found in {source_url}")
            return facts

        rows = target_table.find_all("tr")
        if len(rows) < 3:
            logger.warning(f"HustAnnouncementHtmlParser: too few rows in quota table ({len(rows)})")
            return facts

        top_header = rows[0].find_all(["th", "td"])
        sub_header = rows[1].find_all(["th", "td"])

        # Map column roles from the top header. The merged method column has colspan=3,
        # while name/quota/code each rowspan=2 and occupy single data columns.
        col_idx: dict[str, int] = {}
        method_col_start: Optional[int] = None
        data_col_cursor = 0
        for cell in top_header:
            colspan = int(cell.get("colspan") or 1)
            text = cell.get_text(" ", strip=True)
            text_lower = text.lower()
            if colspan > 1 and ("phương" in text_lower or "thức" in text_lower):
                method_col_start = data_col_cursor
            elif "chương trình" in text_lower or "ngành đào tạo" in text_lower:
                col_idx["name"] = data_col_cursor
            elif "chỉ tiêu" in text_lower:
                col_idx["quota"] = data_col_cursor
            elif "mã xét tuyển" in text_lower or text_lower.strip() == "mã":
                col_idx["code"] = data_col_cursor
            data_col_cursor += colspan

        # Map method sub-columns to data-row positions.
        if method_col_start is not None:
            for offset, cell in enumerate(sub_header):
                tag = cell.get_text(" ", strip=True).lower()
                if "xttn" in tag:
                    col_idx["xttn"] = method_col_start + offset
                elif "đgtd" in tag or "dgtd" in tag:
                    col_idx["dgtd"] = method_col_start + offset
                elif tag.strip() == "thpt":
                    col_idx["thpt"] = method_col_start + offset

        if "name" not in col_idx or "quota" not in col_idx:
            logger.warning(
                f"HustAnnouncementHtmlParser: required columns not found, "
                f"top_header={[c.get_text(' ', strip=True) for c in top_header]!r}"
            )
            return facts

        max_idx = max(col_idx.values())
        for tr in rows[2:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) <= max_idx:
                # Section divider (1 cell) or totals row (e.g. "Tổng chỉ tiêu:") — skip.
                continue
            first_cell = cells[0].strip()
            # Skip rows whose first cell is not a pure index number (handles totals row too).
            if not re.match(r"^\d+\s*$", first_cell):
                continue

            program_name = cells[col_idx["name"]].strip()
            quota_raw = _digits_only(cells[col_idx["quota"]])
            program_code = (
                cells[col_idx["code"]].strip() if "code" in col_idx else None
            ) or None

            if not program_name or not quota_raw:
                continue

            method_flags = []
            for flag_key, label in (
                ("xttn", "xét tuyển tài năng"),
                ("dgtd", "xét tuyển theo KQ Kỳ thi ĐGTD"),
                ("thpt", "xét tuyển theo KQ Kỳ thi TN THPT"),
            ):
                if flag_key in col_idx and _is_method_flag_set(cells[col_idx[flag_key]]):
                    method_flags.append(label)
            admission_method_raw = "; ".join(method_flags) if method_flags else None

            facts.append(
                ExtractedAdmissionFact(
                    school_name=school_name,
                    admission_year=ADMISSION_YEAR,
                    program_name=program_name,
                    program_code=program_code,
                    admission_method_raw=admission_method_raw,
                    subject_combinations_raw=None,
                    quota_raw=quota_raw,
                    source_reference=SourceReference(
                        source_id="hust_announcement_html_2026",
                        source_url=source_url,
                        school_id=school_id,
                        trust_level=5,
                    ),
                    confidence_score=0.9,
                    extraction_method="hust_announcement_html_parser",
                )
            )

        logger.info(f"HustAnnouncementHtmlParser: total {len(facts)} facts from {source_url}")
        return facts
