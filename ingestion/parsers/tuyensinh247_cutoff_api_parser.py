"""Tuyensinh247 cutoff API parser (JSON) — Giai đoạn 2, plan 7.

Endpoint nội bộ trang (nút "Xem thêm" gọi):
GET /api/common/cutoff-score?school_id={id}&method_id={m}&year={y}
→ {"success": true, "data": [{code, name, block, mark, year, admission_name, ...}]}

Ưu thế so với bảng HTML: có MÃ tuyển sinh (code) → map_program stage-code chính xác
tuyệt đối; có tổ hợp (block) cho mọi phương thức. API không phải public contract —
fixture snapshot + source active:false; đổi schema thì trả [] + warning, runner exit 1.

Aggregator (trust 3). Trả ExtractedCutoffFact → chạy qua runner
`ingestion.ingest_cutoffs --source-url`, KHÔNG qua IngestionPipeline.
"""
from __future__ import annotations

import json
import logging
import re
from typing import List, Optional

from ingestion.models.pipeline_models import ExtractedCutoffFact, SourceReference

logger = logging.getLogger(__name__)

_WS_RE = re.compile(r"\s+")


def _norm_ws(value) -> str:
    return _WS_RE.sub(" ", str(value)).strip() if value else ""


class Tuyensinh247CutoffApiParser:
    """Đăng ký qua CUTOFF_PARSERS trong ingest_cutoffs (như parser HTML plan 5)."""

    parser_profile = "tuyensinh247_cutoff_api"

    def parse(
        self,
        content: bytes,
        source_url: str,
        cutoff_year: Optional[int] = None,   # filter tùy chọn; năm thật đọc từ row
        school_id: str = "hust",
        school_name: str = "Đại học Bách khoa Hà Nội",
        trust_level: int = 3,
    ) -> List[ExtractedCutoffFact]:
        try:
            payload = json.loads(content)
        except (ValueError, UnicodeDecodeError):
            logger.warning("Tuyensinh247CutoffApiParser: body không phải JSON từ %s", source_url)
            return []
        if not isinstance(payload, dict):
            logger.warning("Tuyensinh247CutoffApiParser: payload không phải object từ %s", source_url)
            return []
        rows = payload.get("data")
        if not payload.get("success") or not isinstance(rows, list):
            logger.warning(
                "Tuyensinh247CutoffApiParser: payload không hợp lệ (success=%r) từ %s",
                payload.get("success"), source_url,
            )
            return []

        facts: List[ExtractedCutoffFact] = []
        for row in rows:
            name = _norm_ws(row.get("name"))
            mark = row.get("mark")
            year = row.get("year")
            if not name or mark is None or not isinstance(year, int):
                logger.debug("API row thiếu name/mark/year, bỏ qua: %r", row.get("code"))
                continue
            if cutoff_year is not None and year != cutoff_year:
                continue
            code = _norm_ws(row.get("code"))
            # Quirk dữ liệu 2022 của tsn247: mã mang hậu tố method
            # ('y'/'Y' = THPT, 'x' = ĐGTD — vd IT2y, BF1x, TROY-ITy);
            # 2023+ mã sạch, không mã BKA thật nào kết thúc bằng x/y.
            if len(code) > 1 and code[-1] in "xXyY":
                code = code[:-1]
            block = _norm_ws(row.get("block"))
            combos = [s.strip() for s in block.split(";") if s.strip()] or None

            facts.append(
                ExtractedCutoffFact(
                    school_name=school_name,
                    cutoff_year=year,
                    program_name=name,
                    program_code=code or None,
                    admission_method_raw=_norm_ws(row.get("admission_name")) or None,
                    subject_combinations_raw=combos,
                    cutoff_score_raw=str(mark),
                    note_raw=_norm_ws(row.get("introtext")) or None,
                    source_reference=SourceReference(
                        source_id=f"tsn247_api_{school_id}_{year}",
                        source_url=source_url,
                        school_id=school_id,
                        trust_level=trust_level,
                    ),
                    confidence_score=0.85,
                    extraction_method="tuyensinh247_cutoff_api",
                )
            )

        logger.info(
            "Tuyensinh247CutoffApiParser: %d cutoff facts from %s", len(facts), source_url
        )
        return facts
