import re
import json
import logging
from typing import List, Optional, Iterable, Dict, Any, Union
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup, Tag

from ingestion.parsers.base_parser import BaseSpecializedParser
from ingestion.models.pipeline_models import (
    ExtractedAdmissionFact,
    SourceReference,
)
from ingestion.config.settings import ADMISSION_YEAR
from services.text_utils import vietnamese_fold

logger = logging.getLogger(__name__)

_RE_LABEL_PROGRAM_CODE = re.compile(r"\bMã\s+xét\s+tuyển\b", re.IGNORECASE)
_RE_LABEL_LANGUAGE = re.compile(r"\bNgôn\s+ngữ\s+đào\s+tạo\b", re.IGNORECASE)
_RE_LABEL_QUOTA = re.compile(r"\bChỉ\s+tiêu\s+tuyển\s+sinh\b", re.IGNORECASE)
_RE_LABEL_COMBOS = re.compile(r"\bTổ\s+hợp\s+xét\s+tuyển\b", re.IGNORECASE)
_RE_LABEL_DETAIL = re.compile(r"\bChi\s+tiết\b", re.IGNORECASE)


_RE_SUBJECT_COMBO = re.compile(r"\b(DD\d|[ABCDKV]\d{2})\b")

# "55 - 65" / "24–30" tuition ranges (shared by the li + line fallbacks).
_TUITION_RANGE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*[-–]\s*(\d+(?:[.,]\d+)?)")


def _safe_decode_html(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("utf-8", errors="replace")


def _iter_text_lines(tag: Tag) -> Iterable[str]:
    text = tag.get_text(separator="\n", strip=True)
    for line in (l.strip() for l in text.split("\n")):
        if line:
            yield re.sub(r"\s+", " ", line)


def _find_first_line(tag: Tag, pattern: re.Pattern[str]) -> Optional[str]:
    for line in _iter_text_lines(tag):
        if pattern.search(line):
            return line
    return None


def _value_after_colon(line: str) -> str:
    if ":" in line:
        return line.split(":", 1)[1].strip()
    return line.strip()


def _extract_first_int(text: str) -> Optional[int]:
    match = re.search(r"(\d+)", text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _normalize_for_match(text: str) -> str:
    """Normalize tiếng Việt cho keyword matching ("Xét tuyển" -> "xet tuyen")."""
    return vietnamese_fold(text)


def _dedupe_preserve_order(items: List[str]) -> List[str]:
    seen: set[str] = set()
    return [item for item in items if item and not (item in seen or seen.add(item))]


def _extract_tuition_from_li(li: Tag) -> Optional[str]:
    """Extract tuition value from one list item scope."""
    li_text = li.get_text(" ", strip=True)
    normalized = _normalize_for_match(li_text)
    if not any(
        token in normalized
        for token in ("hoc phi", "muc hoc phi", "chi phi", "hoc phi du kien")
    ):
        return None

    strong = li.find("strong")
    if strong:
        strong_text = strong.get_text(" ", strip=True)
        range_match = _TUITION_RANGE_RE.search(strong_text)
        if range_match:
            return f"{range_match.group(1)}-{range_match.group(2)}"
        if strong_text:
            return strong_text

    range_match = _TUITION_RANGE_RE.search(li_text)
    if range_match:
        return f"{range_match.group(1)}-{range_match.group(2)}"

    if ":" in li_text:
        value = li_text.split(":", 1)[1].strip()
        if value:
            return value
    return li_text or None


def _tuition_from_tab1(
    soup: BeautifulSoup, target_program_code: Optional[str] = None
) -> Optional[str]:
    """Fallback 1: the structured "#tab_1 ... ul" tuition list, preferring the
    li that matches the target program code, then any li in that list."""
    tab1_ul = soup.select_one("#tab_1 > div > div.wrap_view > ul")
    if not tab1_ul:
        return None

    li_nodes = tab1_ul.find_all("li", recursive=False)
    if not li_nodes:
        li_nodes = tab1_ul.find_all("li")

    if target_program_code:
        normalized_code = target_program_code.upper()
        matched = []
        for li in li_nodes:
            li_text = li.get_text(" ", strip=True)
            if re.search(rf"\b{re.escape(normalized_code)}\b", li_text.upper()):
                matched.append(li)
        for li in matched:
            tuition = _extract_tuition_from_li(li)
            if tuition:
                return tuition

    for li in li_nodes:
        tuition = _extract_tuition_from_li(li)
        if tuition:
            return tuition
    return None


def _tuition_from_all_lis(soup: BeautifulSoup) -> Optional[str]:
    """Fallback 2: any <li> anywhere in the page that mentions tuition."""
    for li in soup.find_all("li"):
        tuition = _extract_tuition_from_li(li)
        if tuition:
            return tuition
    return None


def _tuition_from_lines(lines: List[str]) -> Optional[str]:
    """Fallback 3: a plain-text line mentioning tuition (range > colon > whole)."""
    for line in lines:
        normalized = _normalize_for_match(line)
        if not any(
            token in normalized
            for token in ("hoc phi", "muc hoc phi", "chi phi", "hoc phi du kien")
        ):
            continue

        cleaned = line.strip()
        if not cleaned:
            continue

        range_match = _TUITION_RANGE_RE.search(cleaned)
        if range_match:
            return f"{range_match.group(1)}-{range_match.group(2)}"
        if ":" in cleaned:
            value = cleaned.split(":", 1)[1].strip()
            if value:
                return value
        return cleaned
    return None


def _tuition_from_segment(lines: List[str]) -> Optional[str]:
    """Fallback 4: a tuition keyword + up to 160 trailing chars anywhere."""
    full_text = "\n".join(lines)
    segment_match = re.search(
        r"(?is)(học\s*phí|hoc\s*phi|chi\s*phí|chi\s*phi)[^\n]{0,160}",
        full_text,
    )
    if segment_match:
        segment = segment_match.group(0).strip()
        if segment:
            return segment
    return None


def _extract_tuition_value(
    soup: BeautifulSoup,
    lines: List[str],
    target_program_code: Optional[str] = None,
) -> str:
    """
    Extract tuition from the "Hoc phi" list item, preferring <strong> content.
    Expected structure: <li>Hoc phi: <strong>55 - 65</strong></li>

    Tries each fallback strategy in order; sentinel when none match.
    """
    return (
        _tuition_from_tab1(soup, target_program_code)
        or _tuition_from_all_lis(soup)
        or _tuition_from_lines(lines)
        or _tuition_from_segment(lines)
        or "Không thông tin"
    )


class HustProgramParser(BaseSpecializedParser):
    """
    Specialized parser for the HUST program listing page.

    The page has repeating blocks like:
      ### [01 - ( BF-E12 ) Kỹ thuật thực phẩm (CT tiên tiến)]
      Ngôn ngữ đào tạo: Tiếng Anh
      Mã xét tuyển: BF-E12
      [K00 ...] [A00 ...] [B00 ...]
      Chỉ tiêu tuyển sinh: 40
      Trường Hóa và Khoa học sự sống
      [Chi tiết](link)
    """

    parser_profile = "hust_programs"

    def parse(
        self,
        content: bytes,
        source_url: str,
        school_id: str = "hust",
        school_name: str = "Đại học Bách khoa Hà Nội",
        source_metadata: Optional[dict] = None,
    ) -> List[ExtractedAdmissionFact]:
        """Parse the HUST program listing page."""
        source_id = f"{school_id}_program_listing"
        metadata = source_metadata or {}
        self._fetch_detail_pages = bool(metadata.get("fetch_detail_pages", True))
        self._detail_cache: Dict[str, Dict[str, Any]] = {}
        self._detail_fetch_cache: Dict[str, Dict[str, Any]] = {}

        html_str = _safe_decode_html(content)

        soup = BeautifulSoup(html_str, "html.parser")


        parsed_url = urlparse(source_url)
        self._base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"


        program_cards = self._find_program_cards(soup)

        if not program_cards:
            logger.warning(
                "No program cards found with CSS selectors, "
                "falling back to text-based extraction"
            )
            return self._fallback_text_extraction(
                html_str, source_url, source_id, school_id, school_name
            )

        facts = []
        for card in program_cards:
            fact = self._parse_card(
                card, source_url, source_id, school_id, school_name
            )
            if fact:
                facts.append(fact)

        logger.info(f"Extracted {len(facts)} programs from {school_name} listing")
        return facts

    def _fetch_detail_payload(
        self,
        detail_url: Optional[str],
        target_program_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetch and parse detail page for one program card."""
        if not detail_url or not getattr(self, "_fetch_detail_pages", True):
            return {}

        code_key = (target_program_code or "").upper().strip()
        cache_key = f"{detail_url}::{code_key}"
        cached = self._detail_cache.get(cache_key)
        if cached is not None:
            return cached

        payload: Dict[str, Any] = {}
        try:
            fetch_cached = self._detail_fetch_cache.get(detail_url)
            if fetch_cached is None:
                from ingestion.fetchers.http_fetcher import http_fetch

                detail_fetch = http_fetch(detail_url)
                fetch_cached = {
                    "raw_content": detail_fetch.raw_content,
                    "resolved_detail_url": detail_fetch.final_url,
                }
                self._detail_fetch_cache[detail_url] = fetch_cached

            payload = self._extract_detail_payload(
                fetch_cached["raw_content"],
                target_program_code=target_program_code,
            )
            payload["resolved_detail_url"] = fetch_cached.get("resolved_detail_url")
        except Exception as error:
            logger.warning(f"Detail fetch failed for {detail_url}: {error}")
            payload = {}

        self._detail_cache[cache_key] = payload
        return payload

    def _extract_detail_payload(
        self,
        html_input: Union[str, bytes],
        target_program_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Extract extra admission fields from detail page HTML."""
        if isinstance(html_input, bytes):
            soup = BeautifulSoup(html_input, "html.parser")
        else:
            soup = BeautifulSoup(html_input, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        lines = [
            re.sub(r"\s+", " ", line).strip()
            for line in soup.get_text(separator="\n", strip=True).split("\n")
            if line.strip()
        ]
        detail_raw_text = "\n".join(lines)

        title = ""
        if soup.title:
            title = soup.title.get_text(" ", strip=True)
        headings = [
            heading.get_text(" ", strip=True)
            for heading in soup.find_all(["h1", "h2", "h3", "h4"])
            if heading.get_text(" ", strip=True)
        ]
        links = [
            {
                "text": anchor.get_text(" ", strip=True),
                "href": anchor.get("href", ""),
            }
            for anchor in soup.find_all("a", href=True)
        ]

        method_lines: List[str] = []
        deadline_raw: Optional[str] = None
        tuition_raw: Optional[str] = _extract_tuition_value(
            soup,
            lines,
            target_program_code=target_program_code,
        )
        condition_lines: List[str] = []

        for line in lines:
            normalized_line = _normalize_for_match(line)

            if normalized_line.startswith("xet tuyen"):
                method_lines.append(line.rstrip(":").strip())

            if deadline_raw is None and any(
                token in normalized_line for token in ("deadline", "thoi han", "han nop", "thoi gian")
            ):
                deadline_raw = line

            if any(
                token in normalized_line for token in ("dieu kien", "yeu cau", "luu y", "tieu chi")
            ):
                condition_lines.append(line)

        return {
            "method_lines": _dedupe_preserve_order(method_lines),
            "deadline_raw": deadline_raw,
            "tuition_raw": tuition_raw,
            "condition_lines": _dedupe_preserve_order(condition_lines)[:10],
            "detail_raw_text": detail_raw_text,
            "detail_raw_document": {
                "title": title,
                "headings": _dedupe_preserve_order(headings),
                "links": links,
            },
        }

    def _find_program_cards(self, soup: BeautifulSoup) -> list:
        """Find all program card elements in the HTML."""
        selectors = [
            "div.training-result__item",
            "div.training-item",
            "div.program-item",
            "div.card",
        ]

        for selector in selectors:
            cards = soup.select(selector)
            if cards:
                logger.debug(
                    f"Found {len(cards)} cards with selector '{selector}'"
                )
                return cards




        candidates: list[Tag] = []
        for node in soup.find_all(string=_RE_LABEL_PROGRAM_CODE):
            if not getattr(node, "parent", None):
                continue
            container = node.parent if isinstance(node.parent, Tag) else None
            for _ in range(6):
                if not container or not isinstance(container, Tag):
                    break
                candidates.append(container)
                container = container.parent if isinstance(container.parent, Tag) else None

        unique: list[Tag] = []
        seen: set[int] = set()
        for tag in sorted(candidates, key=lambda t: len(t.get_text(strip=True))):
            tag_id = id(tag)
            if tag_id in seen:
                continue
            seen.add(tag_id)
            txt = tag.get_text(separator="\n", strip=True)
            if len(_RE_LABEL_PROGRAM_CODE.findall(txt)) != 1:
                continue
            unique.append(tag)

        return unique

    def _extract_program_header(self, card: Tag, text: str):
        """Return (program_name, program_code) from a card's header/labels."""
        header_pattern = r"(\d+)\s*-\s*\(\s*([A-Za-z0-9\-]+)\s*\)\s*(.+?)(?:\n|$)"
        header_match = re.search(header_pattern, text)

        program_name = None
        program_code = None

        if header_match:
            program_code = header_match.group(2).strip()
            program_name = header_match.group(3).strip()
        else:
            code_line = _find_first_line(card, _RE_LABEL_PROGRAM_CODE)
            if code_line:
                code_value = _value_after_colon(code_line)

                code_match = re.search(
                    r"\b([A-Z0-9]{2,}(?:-[A-Z0-9]{1,})+)\b",
                    code_value,
                )
                if not code_match:
                    code_match = re.search(r"\b([A-Z]{2,}\d{1,3})\b", code_value)
                if code_match:
                    program_code = code_match.group(1).strip()

            heading = card.find(["h3", "h4", "h5", "a"])
            if heading:
                name_text = heading.get_text(strip=True)
                name_text = re.sub(r"^\d+\s*-\s*\(.*?\)\s*", "", name_text)
                if name_text:
                    program_name = name_text

        return program_name, program_code

    def _extract_subject_combos(self, card: Tag, text: str) -> List[str]:
        subject_combinations: List[str] = []
        for line in _iter_text_lines(card):
            if _RE_LABEL_COMBOS.search(line):
                subject_combinations.extend(_RE_SUBJECT_COMBO.findall(line))

        if subject_combinations:
            seen_combos: set[str] = set()
            subject_combinations = [
                c for c in subject_combinations
                if not (c in seen_combos or seen_combos.add(c))
            ]
        else:
            subject_combinations = _extract_subject_combinations(text)
        return subject_combinations

    def _extract_admission_methods(self, card: Tag) -> List[str]:
        method_lines: List[str] = []
        for line in _iter_text_lines(card):
            normalized_line = _normalize_for_match(line)
            if normalized_line.startswith("xet tuyen"):
                method_lines.append(line.rstrip(":").strip())
        if method_lines:
            method_lines = _dedupe_preserve_order(method_lines)
        return method_lines

    def _extract_quota(self, card: Tag) -> str:
        quota_line = _find_first_line(card, _RE_LABEL_QUOTA)
        if quota_line:
            quota_value = _value_after_colon(quota_line)
            quota_int = _extract_first_int(quota_value)
            return str(quota_int) if quota_int is not None else "0"
        return "0"

    def _extract_language(self, card: Tag) -> Optional[str]:
        lang_line = _find_first_line(card, _RE_LABEL_LANGUAGE)
        if lang_line:
            language_value = _value_after_colon(lang_line)
            return language_value.strip() if language_value else None
        return None

    def _extract_faculty(self, text: str) -> Optional[str]:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        for line in reversed(lines):
            if _normalize_for_match(line) == "chi tiet":
                continue
            if any(kw in line for kw in ["Trường ", "Khoa ", "Viện "]):
                return line
        return None

    def _fetch_and_merge_detail(
        self, card: Tag, source_url: str, program_code: str, method_lines: List[str]
    ) -> Dict[str, Any]:
        """Resolve the detail link, fetch its payload, and merge method lines.

        Network I/O is confined here (via _fetch_detail_payload)."""
        detail_link = None
        for anchor in card.find_all("a", href=True):
            anchor_label = _normalize_for_match(anchor.get_text(" ", strip=True))
            if anchor_label.startswith("chi tiet"):
                detail_link = anchor
                break
        detail_url = None
        if detail_link and detail_link.get("href"):
            detail_url = urljoin(source_url, detail_link["href"])
        detail_payload = self._fetch_detail_payload(
            detail_url,
            target_program_code=program_code,
        )
        detail_method_lines = detail_payload.get("method_lines", [])
        if detail_method_lines:
            method_lines = _dedupe_preserve_order(method_lines + detail_method_lines)
        return {
            "detail_url": detail_url,
            "detail_payload": detail_payload,
            "admission_method_raw": "; ".join(method_lines) if method_lines else None,
            "deadline_raw": detail_payload.get("deadline_raw"),
            "tuition_raw": detail_payload.get("tuition_raw", "Không thông tin"),
        }

    def _build_conditions(
        self, language, faculty, detail_url, detail_payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        conditions: Dict[str, Any] = {}
        if language:
            conditions["language"] = language
        if faculty:
            conditions["faculty"] = faculty
        if detail_url:
            conditions["detail_url"] = detail_url
        resolved_detail_url = detail_payload.get("resolved_detail_url")
        if resolved_detail_url:
            conditions["resolved_detail_url"] = resolved_detail_url
        detail_conditions = detail_payload.get("condition_lines", [])
        if detail_conditions:
            conditions["detail_conditions"] = detail_conditions
        detail_raw_text = detail_payload.get("detail_raw_text")
        if detail_raw_text:
            conditions["detail_raw_text"] = detail_raw_text
        detail_raw_document = detail_payload.get("detail_raw_document")
        if detail_raw_document:
            conditions["detail_raw_document"] = detail_raw_document
        return conditions

    def _parse_card(
        self,
        card: Tag,
        source_url: str,
        source_id: str,
        school_id: str,
        school_name: str,
    ) -> Optional[ExtractedAdmissionFact]:
        """Parse a single program card into an ExtractedAdmissionFact."""
        text = card.get_text(separator="\n", strip=True)

        program_name, program_code = self._extract_program_header(card, text)
        if not program_code:
            return None

        subject_combinations = self._extract_subject_combos(card, text)
        method_lines = self._extract_admission_methods(card)
        quota_raw = self._extract_quota(card)
        language = self._extract_language(card)
        faculty = self._extract_faculty(text)

        detail = self._fetch_and_merge_detail(
            card, source_url, program_code, method_lines
        )
        detail_url = detail["detail_url"]
        detail_payload = detail["detail_payload"]
        admission_method_raw = detail["admission_method_raw"]
        deadline_raw = detail["deadline_raw"]
        tuition_raw = detail["tuition_raw"]

        conditions = self._build_conditions(
            language, faculty, detail_url, detail_payload
        )

        resolved_detail_url = detail_payload.get("resolved_detail_url")
        record_source_url = resolved_detail_url or detail_url or source_url

        source_ref = SourceReference(
            source_id=source_id,
            source_url=record_source_url,
            school_id=school_id,
            trust_level=5,
        )

        return ExtractedAdmissionFact(
            school_name=school_name,
            admission_year=ADMISSION_YEAR,
            program_name=program_name,
            program_code=program_code,
            admission_method_raw=admission_method_raw,
            subject_combinations_raw=subject_combinations,
            quota_raw=quota_raw,
            deadline_raw=deadline_raw,
            tuition_raw=tuition_raw,
            additional_conditions_raw=(
                json.dumps(conditions, ensure_ascii=False)
                if conditions else None
            ),
            source_reference=source_ref,
            confidence_score=0.85,
            extraction_method="hust_program_parser",
        )

    def _fallback_text_extraction(
        self,
        html_str: str,
        source_url: str,
        source_id: str,
        school_id: str,
        school_name: str,
    ) -> List[ExtractedAdmissionFact]:
        """Fallback text-based extraction when CSS selectors fail."""
        soup = BeautifulSoup(html_str, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)

        block_pattern = r"(\d+)\s*-\s*\(\s*([A-Za-z]{2,}[\-]?[A-Za-z0-9]*)\s*\)\s*(.+?)(?=\d+\s*-\s*\(|$)"
        blocks = re.findall(block_pattern, text, re.DOTALL)

        facts = []
        seen_codes = set()

        for _, code, block_text in blocks:
            if re.match(r"^[A-Z]{1,2}\d{2}$", code):
                continue

            if code.lower() in ("k00k00", "k01k01", "a00a00"):
                continue

            program_name_match = re.match(r"(.+?)(?:\n|Ngôn ngữ)", block_text)
            program_name = (
                program_name_match.group(1).strip()
                if program_name_match
                else block_text.split("\n")[0].strip()
            )

            if not program_name or len(program_name) < 3:
                continue

            if code in seen_codes:
                continue
            seen_codes.add(code)

            combos = _extract_subject_combinations(block_text)
            method_lines: List[str] = []
            for raw_line in (ln.strip() for ln in block_text.split("\n")):
                if not raw_line:
                    continue
                normalized_line = _normalize_for_match(raw_line)
                if normalized_line.startswith("xet tuyen"):
                    method_lines.append(raw_line.rstrip(":").strip())
            if method_lines:
                seen_methods: set[str] = set()
                method_lines = [
                    method for method in method_lines
                    if not (method in seen_methods or seen_methods.add(method))
                ]
            admission_method_raw = "; ".join(method_lines) if method_lines else None

            quota_raw = "0"
            quota_match = re.search(r"Chỉ tiêu[^:]*:\s*(\d+)", block_text)
            if quota_match:
                quota_raw = quota_match.group(1)

            language = None
            lang_match = re.search(
                r"Ngôn ngữ đào tạo:\s*(.+?)(?:\n|$)", block_text
            )
            if lang_match:
                language = lang_match.group(1).strip()

            conditions = {}
            if language:
                conditions["language"] = language

            source_ref = SourceReference(
                source_id=source_id,
                source_url=source_url,
                school_id=school_id,
                trust_level=5,
            )

            fact = ExtractedAdmissionFact(
                school_name=school_name,
                admission_year=ADMISSION_YEAR,
                program_name=program_name,
                program_code=code,
                admission_method_raw=admission_method_raw,
                subject_combinations_raw=combos,
                quota_raw=quota_raw,
                additional_conditions_raw=(
                    json.dumps(conditions, ensure_ascii=False)
                    if conditions else None
                ),
                source_reference=source_ref,
                confidence_score=0.75,
                extraction_method="hust_program_parser_fallback",
            )
            facts.append(fact)

        logger.info(f"Fallback extracted {len(facts)} unique programs")
        return facts




def _extract_subject_combinations(text: str) -> List[str]:
    """
    Extract subject combination codes from text.

    Only matches genuine Vietnamese subject combination codes:
    A00-A16, B00-B08, C00-C04, D01-D15, K00-K01, V00-V01, DD2
    """
    codes = _RE_SUBJECT_COMBO.findall(text)

    seen = set()
    unique = []
    for code in codes:
        if code not in seen:
            seen.add(code)
            unique.append(code)

    return unique
