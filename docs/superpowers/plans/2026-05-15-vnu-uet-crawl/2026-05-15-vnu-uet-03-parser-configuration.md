# VNU-UET Parser Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `dispatch_parser` return usable admission facts (program name, quota, method) for VNU-UET's HTML admission page and the ĐHQGHN proposal PDF, using the simplest parser tier that works.

**Architecture:** Three tiers, stop at first success. Tier 1: default profiles (`default_html` / `default_pdf`) — no code change, just run and inspect. Tier 2: profile-tuning (adjust existing profile config if any). Tier 3: a thin school-specific parser `ingestion/parsers/vnu_uet_admission_parser.py` modelled on `hust_program_parser.py`. Registration in `ingestion/parsers/base_parser.py:_auto_discover` is one import line.

**Tech Stack:** Python, BeautifulSoup4, pdfplumber (already in project dependencies), regex.

**Prerequisite:** Plan 02 complete — `vnu_uet_admission_homepage_2026` and `vnuhn_proposal_pdf_2026` are in the registry.

---

### Task 1: Test Default Profiles (Tier 1)

**Files:**
- Create: `scripts/test_vnu_uet_parser.py` (diagnostic script, committed)
- No parser file changes in Tier 1.

- [ ] **Step 1: Write the parser test script**

Create `scripts/test_vnu_uet_parser.py`:

```python
"""
Diagnostic: run the pipeline fetch+parse step for each VNU-UET source
and print extracted facts. Use this to evaluate parser output quality.
"""
import sys
import json
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from ingestion.pipeline.ingestion_pipeline import IngestionPipeline
from ingestion.fetchers.fetch_dispatcher import dispatch_fetch
from ingestion.router.document_router import route_document
from ingestion.parsers.parser_dispatcher import dispatch_parser
from ingestion.extractors.admission_extractor import extract_admission_facts
from ingestion.models.pipeline_models import ExtractedAdmissionFact

pipeline = IngestionPipeline()
sources = pipeline.registry.get_sources_by_school("vnu_uet")

for source in sources:
    print(f"\n{'='*60}")
    print(f"Source: {source.source_id}")
    print(f"Profile: {source.parser_profile}")
    print(f"URL: {source.root_url}")

    try:
        fetch_result = dispatch_fetch(source)
        doc_type = route_document(fetch_result)
        print(f"Doc type: {doc_type}")

        parsed = dispatch_parser(fetch_result, doc_type, source)

        if isinstance(parsed, list):
            facts = parsed
            print(f"Specialized parser returned {len(facts)} facts directly")
        else:
            print(f"Generic parser returned text ({len(parsed.text)} chars)")
            facts = extract_admission_facts(parsed, source)
            print(f"Extractor produced {len(facts)} facts")

        print(f"\nSample facts (first 3):")
        for fact in facts[:3]:
            print(f"  program_name={fact.program_name!r}")
            print(f"  quota_raw={fact.quota_raw!r}")
            print(f"  method_raw={fact.admission_method_raw!r}")
            print(f"  combos={fact.subject_combinations_raw}")
            print()

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback; traceback.print_exc()
```

- [ ] **Step 2: Run it and inspect output**

```
python scripts/test_vnu_uet_parser.py
```

**Evaluate the output for each source. "Usable" means:**
- `len(facts) >= 3`
- `fact.program_name` is a real Vietnamese program name (not a nav menu item or footer text)
- `fact.quota_raw` is a digit string (`"150"`, `"120"`, etc.) for at least 3 facts
- `fact.admission_method_raw` is non-None for at least some facts

**If BOTH sources produce usable output → Tier 1 is sufficient. Jump to Task 5 (commit). Skip Tasks 2, 3, 4.**

**If the HTML source returns poor output (< 3 facts or garbled program names) → continue to Task 2 for the HTML source.**

**If the PDF source returns poor output → document the limitation. The PDF goes through `extract_admission_facts` which uses LLM extraction as fallback. Check the LLM extractor log output. If LLM fallback also fails, exclude the PDF source per the bail-out in Plan 01 and flag the issue.**

---

### Task 2: Snapshot Raw HTML for Stable Development

**Files:**
- Create: `ingestion/parsers/_fixtures/vnu_uet_admission_page.html`

This step runs only if the HTML source output from Task 1 was insufficient. Snapshotting prevents drift if UET updates their page during parser development.

- [ ] **Step 1: Save the live page as a fixture**

```python
python - <<'EOF'
import sys
sys.path.insert(0, ".")
from ingestion.pipeline.ingestion_pipeline import IngestionPipeline
from ingestion.fetchers.fetch_dispatcher import dispatch_fetch

pipeline = IngestionPipeline()
source = pipeline.registry.get_source("vnu_uet_admission_homepage_2026")
result = dispatch_fetch(source)
with open("ingestion/parsers/_fixtures/vnu_uet_admission_page.html", "wb") as f:
    f.write(result.raw_content)
print(f"Saved {len(result.raw_content)} bytes")
EOF
```

- [ ] **Step 2: Open the fixture and find program containers**

```python
python - <<'EOF'
from bs4 import BeautifulSoup
with open("ingestion/parsers/_fixtures/vnu_uet_admission_page.html", "rb") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

# Print all CSS classes used on div elements (top 30 by frequency)
from collections import Counter
classes = Counter()
for tag in soup.find_all(True):
    for c in tag.get("class", []):
        classes[c] += 1
for cls, count in classes.most_common(30):
    print(f"  .{cls}: {count}")
EOF
```

From the output, identify which CSS class wraps each program entry. Look for classes that appear N times where N matches the number of programs on the page (typically 6–12 for VNU-UET). Write down the selector.

Also run:
```python
python - <<'EOF'
from bs4 import BeautifulSoup
with open("ingestion/parsers/_fixtures/vnu_uet_admission_page.html", "rb") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

# Check tables
tables = soup.find_all("table")
print(f"Tables found: {len(tables)}")
for i, t in enumerate(tables[:3]):
    rows = t.find_all("tr")
    print(f"  Table {i}: {len(rows)} rows")
    if rows:
        print(f"    First row text: {rows[0].get_text()[:100]!r}")
        if len(rows) > 1:
            print(f"    Second row text: {rows[1].get_text()[:100]!r}")
EOF
```

Note down whether programs live in `<table>` rows or `<div>` blocks.

---

### Task 3: Write the Thin School-Specific Parser

**Files:**
- Create: `ingestion/parsers/vnu_uet_admission_parser.py`

This task runs only if Tier 1 default profiles were insufficient for the HTML source. The parser handles the UET admission homepage. The PDF continues using `default_pdf` + LLM extraction.

- [ ] **Step 1: Write the parser file**

Create `ingestion/parsers/vnu_uet_admission_parser.py`:

```python
"""
VNU-UET admission homepage parser.
Target: uet.vnu.edu.vn/tuyen-sinh-dai-hoc/ (and equivalent paths).

Tries CSS selectors in priority order, falls back to regex on full text.
Update _SELECTOR_PRIORITY based on the fixture inspection in Plan 03 Task 2.
"""

import re
import logging
from typing import List, Optional
from urllib.parse import urlparse
from bs4 import BeautifulSoup, Tag

from ingestion.parsers.base_parser import BaseSpecializedParser
from ingestion.models.pipeline_models import ExtractedAdmissionFact, SourceReference
from ingestion.config.settings import ADMISSION_YEAR

logger = logging.getLogger(__name__)

_RE_QUOTA = re.compile(
    r"(?:chỉ\s*tiêu|số\s*lượng|chỉ tiêu tuyển sinh)\s*[:\s]*(\d+)",
    re.IGNORECASE,
)
_RE_PROGRAM_CODE = re.compile(
    r"\b(QHT\d{3,4}|QH[-\s]?\d{4}[-\s]?[A-Z]*\.?\w*)\b",
    re.IGNORECASE,
)
_RE_COMBO = re.compile(r"\b(DD\d|[ABCDKV]\d{2})\b")
_RE_METHOD_THPT = re.compile(
    r"(xét\s+(?:tuyển\s+)?(?:bằng|theo|dựa\s+trên)\s+(?:kết\s+quả\s+)?(?:thi|điểm)\s+(?:TN\s+)?THPT"
    r"|điểm thi TN THPT|kỳ thi tốt nghiệp THPT)",
    re.IGNORECASE,
)
_RE_METHOD_DGNL = re.compile(
    r"(đánh\s+giá\s+năng\s+lực|ĐGNL|bài\s+thi\s+ĐGNL)",
    re.IGNORECASE,
)
_RE_METHOD_TALENT = re.compile(
    r"(tuyển\s+thẳng|xét\s+tuyển\s+tài\s+năng|xét\s+tuyển\s+thẳng)",
    re.IGNORECASE,
)

# Update these selectors based on fixture inspection in Task 2.
# Order matters: first matching selector with quota-bearing containers wins.
_SELECTOR_PRIORITY = [
    "table.ts-nganh tr",        # common in Vietnamese university admission tables
    "div.chuong-trinh-item",    # common div-based card layout
    "div.program-item",
    "div.nganh-hoc",
    "div.entry-content table tr",
    "article table tr",
    "table tr",                 # broad fallback — any table row
]


def _safe_decode(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("utf-8", errors="replace")


def _infer_method(text: str) -> Optional[str]:
    if _RE_METHOD_DGNL.search(text):
        return "đánh giá năng lực"
    if _RE_METHOD_THPT.search(text):
        return "xét điểm thi TN THPT"
    if _RE_METHOD_TALENT.search(text):
        return "tuyển thẳng"
    return None


class VnuUetAdmissionParser(BaseSpecializedParser):
    """Specialized parser for VNU-UET's admission homepage."""

    parser_profile = "vnu_uet_admission_page"

    def parse(
        self,
        content: bytes,
        source_url: str,
        school_id: str = "vnu_uet",
        school_name: str = "Trường Đại học Công nghệ - ĐHQGHN",
        source_metadata: Optional[dict] = None,
    ) -> List[ExtractedAdmissionFact]:
        html = _safe_decode(content)
        soup = BeautifulSoup(html, "html.parser")
        source_id = f"{school_id}_admission_homepage"
        facts: List[ExtractedAdmissionFact] = []

        for selector in _SELECTOR_PRIORITY:
            containers = soup.select(selector)
            if not containers:
                continue
            parsed = self._parse_containers(
                containers, source_url, source_id, school_id, school_name
            )
            if parsed:
                facts.extend(parsed)
                logger.info(
                    f"VnuUetAdmissionParser: {len(parsed)} facts via selector '{selector}'"
                )
                break

        if not facts:
            logger.warning(
                "VnuUetAdmissionParser: no CSS match, falling back to regex on full text"
            )
            facts = self._regex_fallback(
                soup.get_text(separator="\n", strip=True),
                source_url, source_id, school_id, school_name,
            )

        logger.info(
            f"VnuUetAdmissionParser: total {len(facts)} facts from {source_url}"
        )
        return facts

    def _parse_containers(
        self,
        containers: list,
        source_url: str,
        source_id: str,
        school_id: str,
        school_name: str,
    ) -> List[ExtractedAdmissionFact]:
        facts = []
        for container in containers:
            if not isinstance(container, Tag):
                continue
            text = container.get_text(separator=" ", strip=True)
            if not text or len(text) < 15:
                continue

            quota_match = _RE_QUOTA.search(text)
            if not quota_match:
                continue  # skip rows/blocks with no quota signal (headers, footers)

            quota_raw = quota_match.group(1)
            code_match = _RE_PROGRAM_CODE.search(text)
            program_code = code_match.group(1) if code_match else None
            combos = list(dict.fromkeys(_RE_COMBO.findall(text)))
            method_raw = _infer_method(text)

            lines = [l.strip() for l in text.split() if l.strip()]
            # First cell / first substantial phrase before quota mention is program name
            text_before_quota = text[: quota_match.start()].strip()
            name_lines = [
                l.strip()
                for l in text_before_quota.replace("\xa0", " ").split("\n")
                if l.strip() and len(l.strip()) > 5
            ]
            program_name = name_lines[-1] if name_lines else text_before_quota[:80].strip()
            program_name = re.sub(r"^\d+[.\s]+", "", program_name).strip()

            if not program_name or len(program_name) < 5:
                continue

            facts.append(
                ExtractedAdmissionFact(
                    school_name=school_name,
                    admission_year=ADMISSION_YEAR,
                    program_name=program_name,
                    program_code=program_code,
                    admission_method_raw=method_raw,
                    subject_combinations_raw=combos if combos else None,
                    quota_raw=quota_raw,
                    source_reference=SourceReference(
                        source_id=source_id,
                        source_url=source_url,
                        school_id=school_id,
                        trust_level=4,
                    ),
                    confidence_score=0.75,
                    extraction_method="vnu_uet_admission_parser",
                )
            )
        return facts

    def _regex_fallback(
        self,
        text: str,
        source_url: str,
        source_id: str,
        school_id: str,
        school_name: str,
    ) -> List[ExtractedAdmissionFact]:
        facts = []
        for match in _RE_QUOTA.finditer(text):
            start = max(0, match.start() - 300)
            snippet = text[start : match.end() + 100]
            snippet_lines = [
                l.strip() for l in snippet.split("\n") if l.strip() and len(l.strip()) > 8
            ]
            # The program name is typically the last non-empty line before the quota
            pre_lines = [
                l for l in snippet_lines if l not in (match.group(0),)
            ]
            program_name = pre_lines[-1] if pre_lines else None
            if not program_name:
                continue
            program_name = re.sub(r"^\d+[.\s]+", "", program_name).strip()

            facts.append(
                ExtractedAdmissionFact(
                    school_name=school_name,
                    admission_year=ADMISSION_YEAR,
                    program_name=program_name,
                    program_code=None,
                    quota_raw=match.group(1),
                    source_reference=SourceReference(
                        source_id=source_id,
                        source_url=source_url,
                        school_id=school_id,
                        trust_level=4,
                    ),
                    confidence_score=0.55,
                    extraction_method="vnu_uet_admission_parser_fallback",
                )
            )
        return facts
```

- [ ] **Step 2: Adjust `_SELECTOR_PRIORITY` based on fixture inspection**

Open `ingestion/parsers/_fixtures/vnu_uet_admission_page.html` and look at the class names you found in Task 2 Step 2. Move the matching selector to position 0 in `_SELECTOR_PRIORITY`. For example, if the fixture inspection showed that programs live in `div.ts-program-row`, change the list to:

```python
_SELECTOR_PRIORITY = [
    "div.ts-program-row",       # confirmed from fixture inspection 2026-05-15
    "table.ts-nganh tr",
    ...
]
```

---

### Task 4: Register the Thin Parser

**Files:**
- Modify: `ingestion/parsers/base_parser.py` (one import line in `_auto_discover`)
- Modify: `ingestion/registry/seeds/initial_sources.json` (update `parser_profile` for the homepage source)

- [ ] **Step 1: Add the import to `_auto_discover`**

In `ingestion/parsers/base_parser.py`, find `_auto_discover` (currently at line 97). Add the VNU-UET parser import after the HUST one:

Current state of `_auto_discover`:
```python
def _auto_discover(self) -> None:
    try:
        from ingestion.parsers.hust_program_parser import HustProgramParser
        self.register(HustProgramParser())
    except ImportError as e:
        logger.warning(f"Could not load HustProgramParser: {e}")
```

After edit:
```python
def _auto_discover(self) -> None:
    try:
        from ingestion.parsers.hust_program_parser import HustProgramParser
        self.register(HustProgramParser())
    except ImportError as e:
        logger.warning(f"Could not load HustProgramParser: {e}")

    try:
        from ingestion.parsers.vnu_uet_admission_parser import VnuUetAdmissionParser
        self.register(VnuUetAdmissionParser())
    except ImportError as e:
        logger.warning(f"Could not load VnuUetAdmissionParser: {e}")
```

- [ ] **Step 2: Update the homepage source's `parser_profile` in the registry seed**

Open `ingestion/registry/seeds/initial_sources.json`. Find the `vnu_uet_admission_homepage_2026` entry. Change its `parser_profile` from `"default_html"` to `"vnu_uet_admission_page"`.

Before:
```json
"parser_profile": "default_html"
```

After:
```json
"parser_profile": "vnu_uet_admission_page"
```

The `vnuhn_proposal_pdf_2026` entry keeps `"parser_profile": "default_pdf"` — the PDF goes through generic text extraction followed by LLM extraction, no thin parser needed.

---

### Task 5: Verify Parser Output Quality

- [ ] **Step 1: Confirm the parser is registered**

```python
python - <<'EOF'
import sys; sys.path.insert(0, ".")
from ingestion.parsers.base_parser import ParserRegistry
r = ParserRegistry.get_instance()
print("Registered profiles:", r.list_profiles())
assert "vnu_uet_admission_page" in r.list_profiles(), "Parser not registered"
print("PASS")
EOF
```

Expected: `Registered profiles: ['hust_programs', 'vnu_uet_admission_page']` and `PASS`.

- [ ] **Step 2: Run the diagnostic script from Task 1 again**

```
python scripts/test_vnu_uet_parser.py
```

Acceptance criteria for the HTML source:
- `len(facts) >= 3`
- At least 3 facts have a non-None `program_name` that looks like a real Vietnamese program name
- At least 3 facts have a non-None `quota_raw` that is a digit string
- At least 1 fact has a non-None `admission_method_raw`

If `confidence_score` is `0.55` for all facts, the regex fallback triggered — re-check the CSS selector in `_SELECTOR_PRIORITY` against the fixture. Update the selector and re-run.

Acceptance criteria for the PDF source:
- The pipeline fetches and routes the PDF without error
- `extract_admission_facts` returns facts (may be via LLM — check logs for `"Using LLM"`)
- At least 3 facts have `program_name` and `quota_raw` populated

- [ ] **Step 3: Run all existing tests**

```
python -m pytest tests/ingestion/ -v
```

Expected: All existing tests pass. The new parser import must not break anything.

---

### Task 6: Commit Parser Work

- [ ] **Step 1: Commit**

```bash
git add ingestion/parsers/vnu_uet_admission_parser.py \
        ingestion/parsers/base_parser.py \
        ingestion/parsers/_fixtures/vnu_uet_admission_page.html \
        ingestion/registry/seeds/initial_sources.json \
        scripts/test_vnu_uet_parser.py
git commit -m "feat: add VNU-UET admission page parser and register with ParserRegistry"
```

If Tier 1 (default profiles only) was sufficient, commit only the diagnostic script:
```bash
git add scripts/test_vnu_uet_parser.py
git commit -m "docs: add VNU-UET parser diagnostic script (default profiles sufficient)"
```

---

### Self-Check Before Proceeding to Plan 04

- `python scripts/test_vnu_uet_parser.py` produces ≥3 facts with real program names and quota values for the HTML source
- The PDF source either returns facts directly or via LLM extraction (check logs)
- All existing tests pass
- The HUST pipeline still works: `python -m ingestion.main --source hust_program_listing` (if that source exists in your registry) returns facts without error
