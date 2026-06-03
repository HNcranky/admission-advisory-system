# NEU Parser Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `dispatch_parser` return usable admission facts (program name, quota, method) for NEU's HTML admission homepage and the NEU proposal PDF, using the simplest parser tier that works.

**Architecture:** Three tiers, stop at first success. Tier 1: default profiles (`default_html` / `default_pdf`) — no code change, just run and inspect. Tier 2: profile-tuning in config only. Tier 3: a thin school-specific parser `ingestion/parsers/neu_program_parser.py` modelled on `hust_program_parser.py`. Registration in `ingestion/parsers/base_parser.py:_auto_discover` is one import block.

**Tech Stack:** Python, BeautifulSoup4, pdfplumber (already in project dependencies), regex.

**Prerequisite:** Plan 02 complete — `neu_admission_homepage_2026` and `neu_proposal_2026` are in the registry.

---

### Task 1: Test Default Profiles (Tier 1)

**Files:**
- Create: `scripts/test_neu_parser.py` (diagnostic script, committed)
- No parser file changes in Tier 1.

- [ ] **Step 1: Write the parser test script**

Create `scripts/test_neu_parser.py`:

```python
"""
Diagnostic: run the pipeline fetch+parse step for each NEU source
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
sources = pipeline.registry.get_sources_by_school("neu")

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
python scripts/test_neu_parser.py
```

**Evaluate the output for each source. "Usable" means:**
- `len(facts) >= 3`
- `fact.program_name` is a real Vietnamese program name (not a nav menu item or footer text) — e.g., "Tài chính - Ngân hàng", "Kế toán", "Marketing"
- `fact.quota_raw` is a digit string (`"600"`, `"400"`, etc.) for at least 3 facts
- `fact.admission_method_raw` is non-None for at least some facts

**If BOTH sources produce usable output → Tier 1 is sufficient. Jump to Task 5 (commit). Skip Tasks 2, 3, 4.**

**If the HTML source returns poor output (< 3 facts or garbled program names) → continue to Task 2 to snapshot the page and write a thin parser.**

**If the PDF source returns poor output → check the LLM extractor log output. The PDF goes through `extract_admission_facts` which uses LLM extraction as fallback. If LLM fallback also fails, exclude the PDF source per the bail-out in Plan 01 and flag the issue.**

---

### Task 2: Snapshot Raw HTML for Stable Development

**Files:**
- Create: `ingestion/parsers/_fixtures/neu_admission_page.html`

This step runs only if the HTML source output from Task 1 was insufficient. Snapshotting prevents drift if NEU updates their page during parser development.

- [ ] **Step 1: Save the live page as a fixture**

```python
python - <<'EOF'
import sys
sys.path.insert(0, ".")
from ingestion.pipeline.ingestion_pipeline import IngestionPipeline
from ingestion.fetchers.fetch_dispatcher import dispatch_fetch

pipeline = IngestionPipeline()
source = pipeline.registry.get_source("neu_admission_homepage_2026")
result = dispatch_fetch(source)
with open("ingestion/parsers/_fixtures/neu_admission_page.html", "wb") as f:
    f.write(result.raw_content)
print(f"Saved {len(result.raw_content)} bytes")
EOF
```

- [ ] **Step 2: Identify program containers in the fixture**

```python
python - <<'EOF'
from bs4 import BeautifulSoup
from collections import Counter

with open("ingestion/parsers/_fixtures/neu_admission_page.html", "rb") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

# Top 30 CSS classes by frequency
classes = Counter()
for tag in soup.find_all(True):
    for c in tag.get("class", []):
        classes[c] += 1
for cls, count in classes.most_common(30):
    print(f"  .{cls}: {count}")
EOF
```

From the output, identify which CSS class wraps each program entry. Look for classes that appear N times where N matches the number of programs on the page (NEU typically lists 20–50 programs across all faculties). Write down the selector.

Also run:
```python
python - <<'EOF'
from bs4 import BeautifulSoup

with open("ingestion/parsers/_fixtures/neu_admission_page.html", "rb") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

tables = soup.find_all("table")
print(f"Tables found: {len(tables)}")
for i, t in enumerate(tables[:5]):
    rows = t.find_all("tr")
    print(f"  Table {i}: {len(rows)} rows")
    if rows:
        print(f"    First row text: {rows[0].get_text()[:120]!r}")
        if len(rows) > 1:
            print(f"    Second row text: {rows[1].get_text()[:120]!r}")
EOF
```

Note down whether programs live in `<table>` rows or `<div>` blocks, and what the quota field's surrounding text looks like (e.g., column header "Chỉ tiêu" or label "Chỉ tiêu tuyển sinh:").

---

### Task 3: Write the Thin School-Specific Parser

**Files:**
- Create: `ingestion/parsers/neu_program_parser.py`

This task runs only if Tier 1 default profiles were insufficient for the HTML source. The parser handles the NEU admission homepage. The PDF continues using `default_pdf` + LLM extraction.

- [ ] **Step 1: Write the parser file**

Create `ingestion/parsers/neu_program_parser.py`:

```python
"""
NEU admission homepage parser.
Target: tuyensinh.neu.edu.vn (and equivalent paths at neu.edu.vn).

Tries CSS selectors in priority order based on fixture inspection,
falls back to regex on full text. Update _SELECTOR_PRIORITY based
on the fixture inspection in Plan 03 Task 2.
"""

import re
import logging
from typing import List, Optional
from bs4 import BeautifulSoup, Tag

from ingestion.parsers.base_parser import BaseSpecializedParser
from ingestion.models.pipeline_models import ExtractedAdmissionFact, SourceReference
from ingestion.config.settings import ADMISSION_YEAR

logger = logging.getLogger(__name__)

# Quota signal: "chỉ tiêu: 600" or "Chỉ tiêu tuyển sinh 600" or "số lượng: 400"
_RE_QUOTA = re.compile(
    r"(?:chỉ\s*tiêu|số\s*lượng)[:\s]*(\d+)",
    re.IGNORECASE,
)
# NEU program codes: 7-digit MoET codes (e.g., 7340201, 7340301, 7480101)
_RE_PROGRAM_CODE = re.compile(r"\b(7\d{6})\b")
# Subject combination codes (A00-A16, B00, C00-C04, D01-D15, etc.)
_RE_COMBO = re.compile(r"\b(DD\d|[ABCDKV]\d{2})\b")
# Admission method patterns specific to NEU (economics/business school)
_RE_METHOD_THPT = re.compile(
    r"(xét\s+(?:tuyển\s+)?(?:bằng|theo|dựa\s+trên)\s+(?:kết\s+quả\s+)?(?:thi|điểm)\s+(?:TN\s+)?THPT"
    r"|điểm thi TN THPT|kỳ thi tốt nghiệp THPT|xét điểm thi THPT)",
    re.IGNORECASE,
)
_RE_METHOD_SCHOOL_RECORD = re.compile(
    r"(xét\s+(?:tuyển\s+)?(?:theo|bằng)\s+(?:kết\s+quả\s+)?học\s+bạ"
    r"|học\s+bạ\s+THPT|kết\s+quả\s+học\s+tập)",
    re.IGNORECASE,
)
_RE_METHOD_COMBINED = re.compile(
    r"(xét\s+tuyển\s+kết\s+hợp|kết\s+hợp\s+(?:chứng\s+chỉ|IELTS|SAT)"
    r"|ưu\s+tiên\s+(?:IELTS|SAT|chứng\s+chỉ\s+quốc\s+tế))",
    re.IGNORECASE,
)
_RE_METHOD_COMPETENCY = re.compile(
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
    "table.tuyensinh-table tr",      # common class name for NEU admission tables
    "div.chuong-trinh-item",         # div-card layout
    "div.nganh-item",
    "div.program-row",
    "div.entry-content table tr",
    "article table tr",
    "table tr",                      # broad fallback — any table row
]


def _safe_decode(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("utf-8", errors="replace")


def _infer_method(text: str) -> Optional[str]:
    if _RE_METHOD_COMBINED.search(text):
        return "xét tuyển kết hợp"
    if _RE_METHOD_COMPETENCY.search(text):
        return "đánh giá năng lực"
    if _RE_METHOD_THPT.search(text):
        return "xét điểm thi TN THPT"
    if _RE_METHOD_SCHOOL_RECORD.search(text):
        return "xét học bạ THPT"
    if _RE_METHOD_TALENT.search(text):
        return "tuyển thẳng"
    return None


class NeuProgramParser(BaseSpecializedParser):
    """Specialized parser for NEU's admission homepage."""

    parser_profile = "neu_admission_page"

    def parse(
        self,
        content: bytes,
        source_url: str,
        school_id: str = "neu",
        school_name: str = "Trường Đại học Kinh tế Quốc dân",
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
                    f"NeuProgramParser: {len(parsed)} facts via selector '{selector}'"
                )
                break

        if not facts:
            logger.warning(
                "NeuProgramParser: no CSS match, falling back to regex on full text"
            )
            facts = self._regex_fallback(
                soup.get_text(separator="\n", strip=True),
                source_url, source_id, school_id, school_name,
            )

        logger.info(
            f"NeuProgramParser: total {len(facts)} facts from {source_url}"
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

            # Program name: last substantial phrase in text before the quota mention
            text_before_quota = text[: quota_match.start()].strip()
            name_lines = [
                l.strip()
                for l in text_before_quota.replace("\xa0", " ").split("\n")
                if l.strip() and len(l.strip()) > 5
            ]
            program_name = name_lines[-1] if name_lines else text_before_quota[:100].strip()
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
                    extraction_method="neu_program_parser",
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
            pre_lines = [l for l in snippet_lines if l != match.group(0)]
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
                    extraction_method="neu_program_parser_fallback",
                )
            )
        return facts
```

- [ ] **Step 2: Adjust `_SELECTOR_PRIORITY` based on fixture inspection**

Open `ingestion/parsers/_fixtures/neu_admission_page.html` and the class names you found in Task 2 Step 2. Move the matching selector to position 0 in `_SELECTOR_PRIORITY`. For example, if the fixture inspection showed programs live in `table.ts-table tr`, change the list to:

```python
_SELECTOR_PRIORITY = [
    "table.ts-table tr",             # confirmed from fixture inspection 2026-05-15
    "table.tuyensinh-table tr",
    ...
]
```

---

### Task 4: Register the Thin Parser

**Files:**
- Modify: `ingestion/parsers/base_parser.py` (one import block in `_auto_discover`)
- Modify: `ingestion/registry/seeds/initial_sources.json` (update `parser_profile` for the homepage source)

- [ ] **Step 1: Add the import to `_auto_discover`**

In `ingestion/parsers/base_parser.py`, find `_auto_discover`. Add the NEU parser import after the existing ones:

Current state (approximately):
```python
def _auto_discover(self) -> None:
    try:
        from ingestion.parsers.hust_program_parser import HustProgramParser
        self.register(HustProgramParser())
    except ImportError as e:
        logger.warning(f"Could not load HustProgramParser: {e}")
    # (possibly VNU-UET parser here if Plan 03 for VNU-UET was executed)
```

After edit (append after the last existing try/except block):
```python
    try:
        from ingestion.parsers.neu_program_parser import NeuProgramParser
        self.register(NeuProgramParser())
    except ImportError as e:
        logger.warning(f"Could not load NeuProgramParser: {e}")
```

- [ ] **Step 2: Update the homepage source's `parser_profile` in the registry seed**

Open `ingestion/registry/seeds/initial_sources.json`. Find the `neu_admission_homepage_2026` entry. Change its `parser_profile` from `"default_html"` to `"neu_admission_page"`.

Before:
```json
"parser_profile": "default_html"
```

After:
```json
"parser_profile": "neu_admission_page"
```

The `neu_proposal_2026` entry keeps `"parser_profile": "default_pdf"` — the PDF goes through generic text extraction followed by LLM extraction, no thin parser needed.

---

### Task 5: Verify Parser Output Quality

- [ ] **Step 1: Confirm the parser is registered**

```python
python - <<'EOF'
import sys; sys.path.insert(0, ".")
from ingestion.parsers.base_parser import ParserRegistry
r = ParserRegistry.get_instance()
print("Registered profiles:", r.list_profiles())
assert "neu_admission_page" in r.list_profiles(), "Parser not registered"
print("PASS")
EOF
```

Expected: Registered profiles include `'neu_admission_page'` and `PASS`.

- [ ] **Step 2: Run the diagnostic script from Task 1 again**

```
python scripts/test_neu_parser.py
```

Acceptance criteria for the HTML source:
- `len(facts) >= 3`
- At least 3 facts have a non-None `program_name` that looks like a real NEU program name (e.g., "Tài chính - Ngân hàng", "Kế toán", "Marketing")
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

If a thin parser was written (Tasks 2–4 were executed):
```bash
git add ingestion/parsers/neu_program_parser.py \
        ingestion/parsers/base_parser.py \
        ingestion/parsers/_fixtures/neu_admission_page.html \
        ingestion/registry/seeds/initial_sources.json \
        scripts/test_neu_parser.py
git commit -m "feat: add NEU admission page parser and register with ParserRegistry"
```

If Tier 1 (default profiles only) was sufficient:
```bash
git add scripts/test_neu_parser.py
git commit -m "docs: add NEU parser diagnostic script (default profiles sufficient)"
```

---

### Self-Check Before Proceeding to Plan 04

- `python scripts/test_neu_parser.py` produces ≥3 facts with real NEU program names and quota values for the HTML source
- The PDF source either returns facts directly or via LLM extraction (check logs)
- All existing tests pass
- The HUST pipeline is unaffected: running `python -m ingestion.main --school hust` (if HUST is registered) exits without error
