"""
VNU-UET admission homepage parser.

The live homepage is an Elementor page with admission data embedded in
HTML tables. The program rows currently live in a table headed:
STT | Ten nganh/chuong trinh | Ma xet tuyen | So luong tuyen sinh.
"""

import logging
import re
import unicodedata
from typing import Iterable, List, Optional

from bs4 import BeautifulSoup, Tag

from ingestion.config.settings import ADMISSION_YEAR
from ingestion.models.pipeline_models import (
    ExtractedAdmissionFact,
    SourceReference,
)
from ingestion.parsers.base_parser import BaseSpecializedParser

logger = logging.getLogger(__name__)

_SOURCE_ID = "vnu_uet_admission_homepage_2026"

_RE_COMBO = re.compile(r"\b(DD\d|[A-Z]\d{2})\b")
_RE_PROGRAM_CODE = re.compile(r"\b(CN\d{1,2}|QHT\d{3,4}|[A-Z]{2,}\d{2,4})\b")
_RE_QUOTA_VALUE = re.compile(r"\b(\d{1,4})\b")
_RE_SKIP_NAME = re.compile(
    r"\b(tong|tt|stt|ma|ten nganh|phuong thuc|chi tieu|so luong)\b",
    re.IGNORECASE,
)

_SELECTOR_PRIORITY = [
    "div.dev-faq-content table",  # confirmed fixture container for program fact tables
    "table",
    "div.elementor-widget-container table",
    "table tr",
    "div.dev-faq-item",
    "div.dev-tab-item",
]


def _safe_decode(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("utf-8", errors="replace")


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(
        ch for ch in decomposed if not unicodedata.combining(ch)
    )
    # NFKD does not split precomposed Đ/đ; map them explicitly so callers can
    # use ASCII keywords like "dbcl" / "du bi".
    folded = without_marks.translate({ord("Đ"): "D", ord("đ"): "d"})
    return re.sub(r"\s+", " ", folded).lower().strip()


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _dedupe(items: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    unique: List[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _table_rows(table: Tag) -> List[List[str]]:
    rows: List[List[str]] = []
    for tr in table.find_all("tr"):
        cells = [
            _clean_text(cell.get_text(" ", strip=True))
            for cell in tr.find_all(["th", "td"])
        ]
        if any(cells):
            rows.append(cells)
    return rows


def _header_index(header: List[str], aliases: Iterable[str]) -> Optional[int]:
    normalized_header = [_normalize(cell) for cell in header]
    normalized_aliases = [_normalize(alias) for alias in aliases]
    for idx, cell in enumerate(normalized_header):
        if any(alias in cell for alias in normalized_aliases):
            return idx
    return None


def _is_program_quota_table(rows: List[List[str]]) -> bool:
    if not rows:
        return False

    header = rows[0]
    has_name = _header_index(
        header,
        ("ten nganh/chuong trinh", "nganh dao tao", "ten nganh"),
    ) is not None
    has_code = _header_index(
        header,
        ("ma xet tuyen",),
    ) is not None
    has_quota = _header_index(
        header,
        ("so luong tuyen sinh", "so luong", "chi tieu"),
    ) is not None
    is_undergraduate_admission = any(
        "ma xet tuyen" in _normalize(cell) for cell in header
    )

    # Skip the dự bị 1% sub-allocation table (signature column "Ngưỡng ĐBCL").
    if any("nguong dbcl" in _normalize(cell) for cell in header):
        return False

    return has_name and has_code and has_quota and is_undergraduate_admission


def _extract_combinations_from_table(table: Tag) -> List[str]:
    rows = _table_rows(table)
    if not rows:
        return []
    header_norm = " ".join(_normalize(cell) for cell in rows[0])
    if "to hop mon xet tuyen" not in header_norm:
        return []

    combos: List[str] = []
    for row in rows[1:]:
        combos.extend(_RE_COMBO.findall(" ".join(row)))
    return _dedupe(combos)


def _extract_subject_combinations_near_table(table: Tag) -> List[str]:
    for previous_table in table.find_all_previous("table"):
        combos = _extract_combinations_from_table(previous_table)
        if combos:
            return combos
    return []


def _extract_first_subject_combinations_before_2025(soup: BeautifulSoup) -> List[str]:
    for table in soup.select("table"):
        context_text = _clean_text(table.get_text(" ", strip=True))
        if "2025" in context_text and "2026" not in context_text:
            break
        rows = _table_rows(table)
        if not rows:
            continue
        combos = _extract_combinations_from_table(table)
        if combos:
            return combos
    return []


def _extract_global_methods(soup: BeautifulSoup) -> List[str]:
    methods: List[str] = []
    for table in soup.select("table"):
        rows = _table_rows(table)
        if not rows:
            continue
        header_norm = " ".join(_normalize(cell) for cell in rows[0])
        if "phuong thuc" not in header_norm:
            continue
        for row in rows[1:]:
            if len(row) >= 2 and _normalize(row[1]).startswith("xet tuyen"):
                methods.append(row[1])
            elif len(row) == 1 and _normalize(row[0]).startswith("xet tuyen"):
                methods.append(row[0])
    return _dedupe(methods)


def _nearest_method_context(table: Tag) -> Optional[str]:
    for node in table.find_all_previous(
        ["h1", "h2", "h3", "h4", "h5", "p", "strong"],
        limit=10,
    ):
        text = _clean_text(node.get_text(" ", strip=True))
        normalized = _normalize(text)
        if normalized.startswith("2.2.5") and "xet tuyen" in normalized:
            return text
        if normalized.startswith("xet tuyen") or ". xet tuyen" in normalized:
            return text
    return None


def _only_du_bi_quota_signal(soup: BeautifulSoup) -> bool:
    saw_quota_table = False
    for table in soup.select("table"):
        rows = _table_rows(table)
        if not rows:
            continue
        header = rows[0]
        normalized_header = [_normalize(cell) for cell in header]
        looks_like_quota_table = (
            any(
                "ten nganh" in cell or "nganh dao tao" in cell
                for cell in normalized_header
            )
            and any("ma xet tuyen" in cell for cell in normalized_header)
            and any(
                "so luong" in cell or "chi tieu" in cell
                for cell in normalized_header
            )
        )
        if not looks_like_quota_table:
            continue
        saw_quota_table = True
        if not any("nguong dbcl" in cell for cell in normalized_header):
            return False
    return saw_quota_table


def _looks_like_program_name(value: str) -> bool:
    normalized = _normalize(value)
    if len(value) < 5:
        return False
    if _RE_SKIP_NAME.search(normalized):
        return False
    return any(
        token in normalized
        for token in (
            "cong nghe",
            "ky thuat",
            "khoa hoc",
            "tri tue",
            "he thong",
            "mang may",
            "vat ly",
            "co ky",
            "thiet ke",
        )
    )


class VnuUetAdmissionParser(BaseSpecializedParser):
    """Specialized parser for the VNU-UET admission homepage."""

    parser_profile = "vnu_uet_admission_page"

    def parse(
        self,
        content: bytes,
        source_url: str,
        school_id: str = "vnu_uet",
        school_name: str = "Truong Dai hoc Cong nghe - DHQGHN",
        source_metadata: Optional[dict] = None,
    ) -> List[ExtractedAdmissionFact]:
        html = _safe_decode(content)
        soup = BeautifulSoup(html, "html.parser")

        global_methods = _extract_global_methods(soup)
        fallback_subject_combinations = _extract_first_subject_combinations_before_2025(soup)

        # If the only per-program quota signal on the page is the dự bị 1%
        # allocation, the homepage has no full-method quota to emit. Bail out
        # rather than letting the generic/regex fallbacks scrape stray digits.
        if _only_du_bi_quota_signal(soup):
            logger.info(
                "VnuUetAdmissionParser: only dự bị allocation quota table found; "
                "emitting no facts to avoid fabricating method-level conflicts"
            )
            return []

        for selector in _SELECTOR_PRIORITY:
            containers = soup.select(selector)
            if not containers:
                continue
            if selector.endswith("table") or selector == "table":
                facts = self._parse_tables(
                    containers,
                    source_url,
                    school_id,
                    school_name,
                    global_methods,
                )
            else:
                facts = self._parse_generic_containers(
                    containers,
                    source_url,
                    school_id,
                    school_name,
                    fallback_subject_combinations,
                    global_methods,
                )
            if facts:
                logger.info(
                    "VnuUetAdmissionParser: extracted %s facts via selector %r",
                    len(facts),
                    selector,
                )
                return facts

        logger.warning(
            "VnuUetAdmissionParser: no CSS table/container match; using text fallback"
        )
        return self._regex_fallback(
            soup.get_text("\n", strip=True),
            source_url,
            school_id,
            school_name,
            fallback_subject_combinations,
            global_methods,
        )

    def _parse_tables(
        self,
        tables: List[Tag],
        source_url: str,
        school_id: str,
        school_name: str,
        global_methods: List[str],
    ) -> List[ExtractedAdmissionFact]:
        for table in tables:
            rows = _table_rows(table)
            if not _is_program_quota_table(rows):
                continue

            header = rows[0]
            name_idx = _header_index(
                header,
                ("ten nganh/chuong trinh", "nganh dao tao", "ten nganh"),
            )
            code_idx = _header_index(header, ("ma xet tuyen",))
            quota_idx = _header_index(
                header,
                ("so luong tuyen sinh", "so luong", "chi tieu"),
            )
            if name_idx is None or quota_idx is None:
                continue

            table_method = _nearest_method_context(table)
            admission_method_raw = table_method or "; ".join(global_methods) or None
            subject_combinations = _extract_subject_combinations_near_table(table)
            facts: List[ExtractedAdmissionFact] = []

            for row in rows[1:]:
                fact = self._fact_from_table_row(
                    row,
                    name_idx,
                    code_idx,
                    quota_idx,
                    source_url,
                    school_id,
                    school_name,
                    subject_combinations,
                    admission_method_raw,
                )
                if fact:
                    facts.append(fact)

            if facts:
                return facts

        return []

    def _fact_from_table_row(
        self,
        row: List[str],
        name_idx: int,
        code_idx: Optional[int],
        quota_idx: int,
        source_url: str,
        school_id: str,
        school_name: str,
        subject_combinations: List[str],
        admission_method_raw: Optional[str],
    ) -> Optional[ExtractedAdmissionFact]:
        if len(row) <= max(name_idx, quota_idx):
            return None

        program_name = _clean_text(row[name_idx])
        if not _looks_like_program_name(program_name):
            return None

        quota_match = _RE_QUOTA_VALUE.search(row[quota_idx])
        if not quota_match:
            return None
        quota_raw = quota_match.group(1)

        program_code = None
        if code_idx is not None and len(row) > code_idx:
            code_match = _RE_PROGRAM_CODE.search(row[code_idx])
            if code_match:
                program_code = code_match.group(1)

        return self._build_fact(
            source_url=source_url,
            school_id=school_id,
            school_name=school_name,
            program_name=program_name,
            program_code=program_code,
            quota_raw=quota_raw,
            admission_method_raw=admission_method_raw,
            subject_combinations=subject_combinations,
            confidence_score=0.86,
            extraction_method="vnu_uet_admission_parser_table",
        )

    def _parse_generic_containers(
        self,
        containers: List[Tag],
        source_url: str,
        school_id: str,
        school_name: str,
        subject_combinations: List[str],
        global_methods: List[str],
    ) -> List[ExtractedAdmissionFact]:
        facts: List[ExtractedAdmissionFact] = []
        method_raw = "; ".join(global_methods) or None
        for container in containers:
            text = _clean_text(container.get_text(" ", strip=True))
            if not text:
                continue
            quota_match = re.search(
                r"(?:chi tieu|so luong tuyen sinh|so luong)\D{0,30}(\d{1,4})",
                _normalize(text),
            )
            if not quota_match:
                continue
            code_match = _RE_PROGRAM_CODE.search(text)
            if not code_match:
                continue
            before_code = text[: code_match.start()].strip()
            program_name = before_code.split(".")[-1].strip()
            if not _looks_like_program_name(program_name):
                continue
            facts.append(
                self._build_fact(
                    source_url=source_url,
                    school_id=school_id,
                    school_name=school_name,
                    program_name=program_name,
                    program_code=code_match.group(1),
                    quota_raw=quota_match.group(1),
                    admission_method_raw=method_raw,
                    subject_combinations=subject_combinations,
                    confidence_score=0.66,
                    extraction_method="vnu_uet_admission_parser_container",
                )
            )
        return facts

    def _regex_fallback(
        self,
        text: str,
        source_url: str,
        school_id: str,
        school_name: str,
        subject_combinations: List[str],
        global_methods: List[str],
    ) -> List[ExtractedAdmissionFact]:
        facts: List[ExtractedAdmissionFact] = []
        method_raw = "; ".join(global_methods) or None
        row_pattern = re.compile(
            r"(?m)^\s*\d+\.?\s+(.{5,120}?)\s+(CN\d{1,2})\s+(\d{1,4})(?:\s|$)"
        )
        for match in row_pattern.finditer(text):
            program_name = _clean_text(match.group(1))
            if not _looks_like_program_name(program_name):
                continue
            facts.append(
                self._build_fact(
                    source_url=source_url,
                    school_id=school_id,
                    school_name=school_name,
                    program_name=program_name,
                    program_code=match.group(2),
                    quota_raw=match.group(3),
                    admission_method_raw=method_raw,
                    subject_combinations=subject_combinations,
                    confidence_score=0.55,
                    extraction_method="vnu_uet_admission_parser_fallback",
                )
            )
        return facts

    def _build_fact(
        self,
        source_url: str,
        school_id: str,
        school_name: str,
        program_name: str,
        program_code: Optional[str],
        quota_raw: str,
        admission_method_raw: Optional[str],
        subject_combinations: List[str],
        confidence_score: float,
        extraction_method: str,
    ) -> ExtractedAdmissionFact:
        return ExtractedAdmissionFact(
            school_name=school_name,
            admission_year=ADMISSION_YEAR,
            program_name=program_name,
            program_code=program_code,
            admission_method_raw=admission_method_raw,
            subject_combinations_raw=subject_combinations or None,
            quota_raw=quota_raw,
            source_reference=SourceReference(
                source_id=_SOURCE_ID,
                source_url=source_url,
                school_id=school_id,
                trust_level=4,
            ),
            confidence_score=confidence_score,
            extraction_method=extraction_method,
        )
