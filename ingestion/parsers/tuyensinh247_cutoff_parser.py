"""Tuyensinh247 cutoff (điểm chuẩn) HTML parser — Giai đoạn 2.

Trang https://diemthi.tuyensinh247.com/diem-chuan/<slug>.html: mỗi phương thức một bảng
`Tên ngành | Tổ hợp môn | Điểm chuẩn | Ghi chú` đứng sau heading h3
"Điểm chuẩn theo phương thức {X} năm {Y}". Layout chung mọi trường → parser generic;
thêm trường mới chỉ cần thêm entry initial_sources.json.

Aggregator (trust 3) — nguồn phụ bên cạnh seed chính thức (trust 5).
Trả ExtractedCutoffFact (KHÔNG phải ExtractedAdmissionFact) — vì vậy parser này chạy
qua runner `ingestion.ingest_cutoffs --source-url`, KHÔNG qua IngestionPipeline.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional

from bs4 import BeautifulSoup

from ingestion.models.pipeline_models import ExtractedCutoffFact, SourceReference

logger = logging.getLogger(__name__)

# get_text(" ", strip=True) chèn space giữa các element con của h3;
# regex vẫn chịu được trường hợp dính liền ("phương thứcĐiểm thi THPTnăm2025").
_HEADING_RE = re.compile(
    r"điểm chuẩn theo phương thức\s*(.+?)\s*năm\s*(20\d{2})", re.IGNORECASE
)
_SCORE_RE = re.compile(r"^\d{1,3}([.,]\d{1,2})?$")


class Tuyensinh247CutoffParser:
    """Không kế thừa BaseSpecializedParser vì trả ExtractedCutoffFact (khác kiểu).

    Đăng ký riêng qua CUTOFF_PARSERS trong ingest_cutoffs (không vào ParserRegistry
    của pipeline chính — tránh dispatch nhầm sang đường admission facts).
    """

    parser_profile = "tuyensinh247_cutoff_html"

    def parse(
        self,
        content: bytes,
        source_url: str,
        cutoff_year: Optional[int] = None,   # filter tùy chọn; năm thật đọc từ heading
        school_id: str = "hust",
        school_name: str = "Đại học Bách khoa Hà Nội",
        trust_level: int = 3,
    ) -> List[ExtractedCutoffFact]:
        facts: List[ExtractedCutoffFact] = []
        soup = BeautifulSoup(content, "html.parser")

        for h3 in soup.find_all("h3"):
            m = _HEADING_RE.search(h3.get_text(" ", strip=True))
            if not m:
                continue
            method_raw, year = m.group(1).strip(), int(m.group(2))
            if cutoff_year is not None and year != cutoff_year:
                continue
            table = h3.find_next("table")
            if table is None:
                logger.warning(
                    "Tuyensinh247CutoffParser: heading %r không có bảng kèm theo", method_raw
                )
                continue
            facts.extend(
                self._parse_table(
                    table, method_raw, year, source_url, school_id, school_name, trust_level
                )
            )

        logger.info(
            "Tuyensinh247CutoffParser: %d cutoff facts from %s", len(facts), source_url
        )
        return facts

    def _parse_table(
        self, table, method_raw, year, source_url, school_id, school_name, trust_level
    ) -> List[ExtractedCutoffFact]:
        rows = table.find_all("tr")
        if not rows:
            return []
        header = [c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"])]
        col: dict[str, Optional[int]] = {"name": None, "combo": None, "score": None, "note": None}
        for i, text in enumerate(header):
            if "tên ngành" in text or "ngành" in text:
                col["name"] = col["name"] if col["name"] is not None else i
            elif "tổ hợp" in text:
                col["combo"] = i
            elif "điểm chuẩn" in text or "điểm trúng tuyển" in text:
                col["score"] = i
            elif "ghi chú" in text:
                col["note"] = i
        if col["name"] is None or col["score"] is None:
            logger.warning(
                "Tuyensinh247CutoffParser: bảng %r thiếu cột bắt buộc, header=%r",
                method_raw, header,
            )
            return []

        facts: List[ExtractedCutoffFact] = []
        for tr in rows[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) <= col["score"]:
                continue  # row rác "Tra cứu tại..." (colspan) / divider
            score_raw = cells[col["score"]].strip()
            if not _SCORE_RE.match(score_raw):
                continue
            program_name = cells[col["name"]].strip()
            if not program_name:
                continue
            combos_text = cells[col["combo"]].strip() if col["combo"] is not None and len(cells) > col["combo"] else ""
            combos = [s.strip() for s in combos_text.split(";") if s.strip()] or None
            note = (cells[col["note"]].strip() if col["note"] is not None and len(cells) > col["note"] else "") or None

            facts.append(
                ExtractedCutoffFact(
                    school_name=school_name,
                    cutoff_year=year,
                    program_name=program_name,
                    program_code=None,  # trang không có mã xét tuyển
                    admission_method_raw=method_raw,
                    subject_combinations_raw=combos,
                    cutoff_score_raw=score_raw,
                    note_raw=note,
                    source_reference=SourceReference(
                        source_id=f"tsn247_cutoff_{school_id}_{year}",
                        source_url=source_url,
                        school_id=school_id,
                        trust_level=trust_level,
                    ),
                    confidence_score=0.85,  # aggregator — thấp hơn parser nguồn chính thức (0.9)
                    extraction_method="tuyensinh247_cutoff_parser",
                )
            )
        return facts
