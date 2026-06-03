# HUST Parser Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `dispatch_parser` return usable admission facts (program name, quota, method) for both HUST sources, using the simplest parser tier that works. Critically, the HUST program listing's `admission_method = None` issue (called out in the spec) must be resolved so canonical rows from both sources group on the same key (even though for HUST 2026 the quota values are not expected to diverge — see Plan 01 pre-flight override).

**Architecture:** Three tiers, stop at first success. Tier 1: existing `hust_programs` parser for Source #1 + generic HTML fallback for Source #2 — no code change. Tier 2: small tweak to `HustProgramParser` to set a non-null `admission_method_raw` when subject combinations are present (fixes the `method=None` grouping collapse). Tier 3: thin school-specific HTML parser `ingestion/parsers/hust_announcement_html_parser.py` modelled on existing BS4 parsers, targeting the 78-row quota `<table>` in the 2026 announcement article. Registration in `ingestion/parsers/base_parser.py:_auto_discover` is one import block per new parser.

**Tech Stack:** Python, BeautifulSoup4, regex.

**Prerequisite:** Plan 02 complete — `hust_program_listing_2026` and `hust_announcement_html_2026` are in the `source_registry` table.

---

### Task 1: Test Default Profiles (Tier 1)

**Files:**
- Create: `scripts/test_hust_parser.py` (diagnostic script, committed)
- No parser file changes in Tier 1.

- [ ] **Step 1: Write the diagnostic script**

Create `scripts/test_hust_parser.py`:

```python
"""
Diagnostic: run the pipeline fetch+parse step for each HUST source
and print extracted facts. Use this to evaluate parser output quality.
"""
import sys
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
sources = pipeline.registry.get_sources_by_school("hust")

for source in sources:
    print(f"\n{'='*60}")
    print(f"Source: {source.source_id}")
    print(f"Profile: {source.parser_profile}")
    print(f"URL: {source.root_url}")

    try:
        fetch_result = dispatch_fetch(source.root_url, source)
        doc_type = route_document(fetch_result)
        print(f"Doc type: {doc_type}")

        parsed = dispatch_parser(fetch_result, doc_type, source)

        if isinstance(parsed, list):
            facts = parsed
            print(f"Specialized parser returned {len(facts)} facts directly")
        else:
            print(f"Generic parser returned text ({len(parsed.text)} chars)")
            from ingestion.models.pipeline_models import SourceReference
            source_ref = SourceReference(
                source_id=source.source_id,
                source_url=source.root_url,
                school_id=source.school_id,
                trust_level=source.trust_level,
            )
            facts = extract_admission_facts(parsed, source_ref, source.school_name)
            print(f"Extractor produced {len(facts)} facts")

        print(f"\nSample facts (first 5):")
        for fact in facts[:5]:
            print(f"  program_name={fact.program_name!r}")
            print(f"  program_code={fact.program_code!r}")
            print(f"  quota_raw={fact.quota_raw!r}")
            print(f"  method_raw={fact.admission_method_raw!r}")
            print(f"  combos={fact.subject_combinations_raw}")
            print()

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback; traceback.print_exc()
```

- [ ] **Step 2: Run it and inspect output**

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe scripts/test_hust_parser.py
```

**Acceptance per source:**

For Source #1 (program listing, `hust_programs`):
- `len(facts) >= 10`
- ≥10 facts have a real Vietnamese `program_name`
- ≥10 facts have a `program_code` like `IT1`, `IT2`, `ET1`, `ME2`, etc.
- ≥10 facts have a `quota_raw` digit string
- Note whether `admission_method_raw` is `None` — this is the known issue.

For Source #2 (the 2026 announcement HTML article, registry profile `hust_announcement_html` — but until Plan 03 Task 4 lands, the registry value resolves to no specialized parser and the generic HTML route runs):
- The pipeline fetches and routes without error
- The generic HTML extractor returns a `ParsedContent` with non-empty `text` containing program names and numbers
- `extract_admission_facts` (LLM fallback) may produce usable facts — check log for `"Using LLM"` lines.
- Realistically, the 78-row table is large and embedded in long article markup; the LLM fallback is unlikely to consistently produce ≥60 program rows. Expect to need Tier 3.

**Decision branching:**

- **If Source #1 produces ≥10 facts AND `admission_method_raw` is non-None for ≥10 of them AND Source #2 produces ≥3 usable facts → skip to Task 5 (commit). Tier 1 is sufficient.**
- **If Source #1 produces ≥10 facts but `admission_method_raw` is None for all → continue to Task 2 (tier-2 fix for the method-grouping risk). Then evaluate Source #2.**
- **If Source #2 returns garbled text or zero usable facts → continue to Task 3 (snapshot announcement HTML) then Task 4 (school-specific HTML parser).**

---

### Task 2: Fix `HustProgramParser` `admission_method_raw = None` (Tier 2)

**Files:**
- Modify: `ingestion/parsers/hust_program_parser.py`

This task runs **only if** Task 1 showed `admission_method_raw` is `None` for all facts from Source #1. The spec calls this out as the HUST-specific risk that can collapse the conflict signal.

- [ ] **Step 1: Write a failing test that pins down the desired behavior**

Add a test to `tests/ingestion/test_hust_program_parser.py` (create if absent):

```python
"""Tests for HustProgramParser, focused on the method-grouping fix."""

from pathlib import Path

from ingestion.parsers.hust_program_parser import HustProgramParser


def _load_fixture() -> bytes:
    fixture_path = (
        Path(__file__).parent.parent.parent
        / "ingestion" / "parsers" / "_fixtures" / "hust_program_card.html"
    )
    return fixture_path.read_bytes()


def test_admission_method_defaults_to_thpt_score_when_combos_present():
    """
    Lesson learned: if HustProgramParser leaves admission_method_raw=None for
    program cards that list THPT subject combinations like A00, B00, then
    canonical rows from this source group on admission_method=NULL and
    cannot share a join key with rows from the announcement-HTML source
    (which carries explicit method-flag labels). Force a sensible default
    so both sources land on the same canonical key.
    """
    parser = HustProgramParser()
    facts = parser.parse(
        content=_load_fixture(),
        source_url="https://ts.hust.edu.vn/training-cate/nganh-dao-tao-dai-hoc",
        school_id="hust",
        school_name="Đại học Bách khoa Hà Nội",
    )
    assert facts, "fixture parse produced no facts — check fixture content"
    facts_with_combos = [f for f in facts if f.subject_combinations_raw]
    assert facts_with_combos, "fixture has no programs with subject combinations"
    methodless = [
        f for f in facts_with_combos if not f.admission_method_raw
    ]
    assert not methodless, (
        f"{len(methodless)} facts with subject combinations are missing "
        f"admission_method_raw — would collapse conflict-grouping on NULL"
    )
```

- [ ] **Step 2: Run the test and confirm it fails**

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe -m pytest tests/ingestion/test_hust_program_parser.py -v
```

Expected: the test fails because the parser currently leaves `admission_method_raw` empty for the program-card fixture.

- [ ] **Step 3: Implement the minimal fix in `HustProgramParser._parse_card`**

Open `ingestion/parsers/hust_program_parser.py`. Locate the line in `_parse_card` that sets `admission_method_raw`:

```python
admission_method_raw = "; ".join(method_lines) if method_lines else None
```

Replace it with:

```python
admission_method_raw = "; ".join(method_lines) if method_lines else None
# Method fallback: if the card lists THPT subject combinations but no explicit
# method line, this row represents the standard THPT-score pathway. Without
# this default, canonical rows would group on admission_method=NULL and
# silently merge with conflict rows from other sources that carry a method
# label. See spec docs/superpowers/specs/2026-05-26-hust-ingestion-design.md
# Step 4 ("admission_method = None collapses the conflict signal").
if not admission_method_raw and subject_combinations:
    admission_method_raw = "xét điểm thi TN THPT"
```

The same fallback should apply in `_fallback_text_extraction`. Locate the equivalent line there and apply the same change:

```python
admission_method_raw = "; ".join(method_lines) if method_lines else None
if not admission_method_raw and combos:
    admission_method_raw = "xét điểm thi TN THPT"
```

- [ ] **Step 4: Run the test and confirm it passes**

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe -m pytest tests/ingestion/test_hust_program_parser.py -v
```

Expected: PASS.

- [ ] **Step 5: Run the diagnostic again**

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe scripts/test_hust_parser.py
```

Expected: Source #1 facts now have `admission_method_raw="xét điểm thi TN THPT"` for cards that list combinations. The string normalizes to `thpt_score` via the `_shared` method dictionary (verified in Plan 04).

- [ ] **Step 6: Confirm no regression in the existing HUST tests**

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe -m pytest tests/ingestion/ -v
```

Expected: all green. The existing `test_db_writer.py` HUST mock records use explicit method strings, so this change is additive.

---

### Task 3: Snapshot the Source #2 Announcement HTML for Stable Development

**Files:**
- Create: `ingestion/parsers/_fixtures/hust_announcement_2026.html`

This task runs **only if** Task 1 showed Source #2 output was insufficient. Snapshotting prevents drift if the article is edited mid-development.

- [ ] **Step 1: Save the live HTML as a fixture**

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe -c "
from ingestion.fetchers.http_fetcher import http_fetch
from pathlib import Path
url = 'https://ts.hust.edu.vn/tin-tuc/thong-tin-tuyen-sinh-dai-hoc-chinh-quy-nam-2026'
r = http_fetch(url)
out = Path('ingestion/parsers/_fixtures/hust_announcement_2026.html')
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(r.raw_content)
print(f'Saved {len(r.raw_content)} bytes to {out}')
"
```

- [ ] **Step 2: Inspect HTML table structure with BeautifulSoup**

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe -c "
from bs4 import BeautifulSoup
HTML = 'ingestion/parsers/_fixtures/hust_announcement_2026.html'
soup = BeautifulSoup(open(HTML, encoding='utf-8').read(), 'html.parser')
tables = soup.find_all('table')
print(f'tables found: {len(tables)}')
for idx, t in enumerate(tables):
    rows = t.find_all('tr')
    cells0 = [c.get_text(strip=True) for c in rows[0].find_all(['td','th'])] if rows else []
    print(f'  table {idx}: {len(rows)} rows, first-row cells = {cells0}')
    if any('Chỉ tiêu' in c for c in cells0):
        print(f'    --> first 3 data rows:')
        for r in rows[1:4]:
            print('     ', [c.get_text(strip=True) for c in r.find_all(['td','th'])])
"
```

Expected per pre-flight findings: table #2 has 78 rows with columns `TT | Chương trình/ngành đào tạo | Chỉ tiêu dự kiến | Mã xét tuyển | XTTN | ĐGTD | THPT`. Section dividers (`A. CHƯƠNG TRÌNH CHUẨN`, `B. CHƯƠNG TRÌNH CHẤT LƯỢNG CAO - ELITECH...`) appear as full-width rows with non-numeric first cell. Final `Tổng chỉ tiêu: 9.880` row is a totals footer. Method columns are the glyph `Ö` (not "Có"/"Không"). Document the index of the quota table — Task 4 will hardcode it (or use the "first table containing 'Chỉ tiêu' in its header" heuristic).

---

### Task 4: Write the Thin HUST Announcement HTML Parser (Tier 3)

**Files:**
- Create: `ingestion/parsers/hust_announcement_html_parser.py`

This task runs **only if** the generic HTML route in Task 1 + LLM fallback fails to produce usable facts (≥60 of the 68 programs). The 2026 announcement table is large; expect to need this.

- [ ] **Step 1: Open existing BS4-based parsers as templates**

```powershell
Get-Content ingestion/parsers/hust_program_parser.py -TotalCount 60
```

Read through to understand the shape: `parser_profile` class attribute, `parse()` method signature, BS4 traversal, row-to-fact emission. The new parser is simpler — single table, fixed columns.

- [ ] **Step 2: Create the HUST announcement HTML parser file**

Create `ingestion/parsers/hust_announcement_html_parser.py`:

```python
"""
HUST 2026 admission announcement HTML parser.

Source: https://ts.hust.edu.vn/tin-tuc/thong-tin-tuyen-sinh-dai-hoc-chinh-quy-nam-2026

The article body contains a single quota table with 78 rows. Columns are:
  TT | Chương trình/ngành đào tạo | Chỉ tiêu dự kiến | Mã xét tuyển | XTTN | ĐGTD | THPT

Method columns (XTTN / ĐGTD / THPT) contain the glyph 'Ö' to flag eligibility;
they are NOT numeric quotas. We emit one fact per program-row with the
program-total quota (column "Chỉ tiêu dự kiến"). Section divider rows
(e.g. "A. CHƯƠNG TRÌNH CHUẨN") and the "Tổng chỉ tiêu: 9.880" totals row
are skipped (their first cell is non-numeric).
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
    """Detect the quota table by its header row containing 'Chỉ tiêu'."""
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
        header_cells = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]

        # Build column index map from observed header text fragments.
        col_idx: dict[str, int] = {}
        for i, h in enumerate(header_cells):
            h_lower = h.lower()
            if "chương trình" in h_lower or "ngành đào tạo" in h_lower:
                col_idx.setdefault("name", i)
            if "chỉ tiêu" in h_lower:
                col_idx.setdefault("quota", i)
            if "mã xét tuyển" in h_lower or h_lower.strip() == "mã":
                col_idx.setdefault("code", i)
            if "xttn" in h_lower:
                col_idx["xttn"] = i
            if "đgtd" in h_lower:
                col_idx["dgtd"] = i
            if h_lower.strip() == "thpt":
                col_idx["thpt"] = i

        if "name" not in col_idx or "quota" not in col_idx:
            logger.warning(
                f"HustAnnouncementHtmlParser: required columns not found, "
                f"header={header_cells!r}"
            )
            return facts

        for tr in rows[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) < max(col_idx.values()) + 1:
                continue
            first_cell = cells[0].strip()
            # Skip section dividers (first cell is non-numeric) and totals row.
            if not re.match(r"^\d+\s*$", first_cell):
                continue
            if first_cell == "" and "Tổng" in " ".join(cells):
                continue

            program_name = cells[col_idx["name"]].strip()
            quota_raw = _digits_only(cells[col_idx["quota"]])
            program_code = (
                cells[col_idx["code"]].strip() if "code" in col_idx else None
            ) or None

            if not program_name or not quota_raw:
                continue

            # Method flags: collect the methods this program is eligible for.
            method_flags = []
            for flag_key, label in (
                ("xttn", "xét tuyển tài năng"),
                ("dgtd", "đánh giá tư duy"),
                ("thpt", "xét điểm thi TN THPT"),
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
```

- [ ] **Step 3: Run the parser against the fixture and verify counts**

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe -c "
from pathlib import Path
from ingestion.parsers.hust_announcement_html_parser import HustAnnouncementHtmlParser
content = Path('ingestion/parsers/_fixtures/hust_announcement_2026.html').read_bytes()
parser = HustAnnouncementHtmlParser()
facts = parser.parse(content=content, source_url='https://ts.hust.edu.vn/tin-tuc/thong-tin-tuyen-sinh-dai-hoc-chinh-quy-nam-2026')
print(f'facts: {len(facts)}')
for f in facts[:5]:
    print(f'  {f.program_name!r} code={f.program_code!r} quota={f.quota_raw!r} method={f.admission_method_raw!r}')
"
```

Expected: ≥60 facts (pre-flight noted 68 programs in the table). Each fact has non-empty `program_name`, digit-only `quota_raw`, and `admission_method_raw` reflecting the flagged methods. If `facts == 0`, the table detection failed — inspect with Task 3 Step 2 again and adjust `_is_quota_table` or column-detection logic.

- [ ] **Step 4: Add a unit test for the new parser**

Create `tests/ingestion/test_hust_announcement_html_parser.py`:

```python
"""Tests for HustAnnouncementHtmlParser against the captured fixture HTML."""
from pathlib import Path
import pytest

from ingestion.parsers.hust_announcement_html_parser import HustAnnouncementHtmlParser


FIXTURE = (
    Path(__file__).parent.parent.parent
    / "ingestion" / "parsers" / "_fixtures" / "hust_announcement_2026.html"
)


@pytest.mark.skipif(not FIXTURE.exists(), reason="Fixture HTML not snapshotted")
def test_parses_full_program_table():
    parser = HustAnnouncementHtmlParser()
    facts = parser.parse(
        content=FIXTURE.read_bytes(),
        source_url="https://ts.hust.edu.vn/tin-tuc/thong-tin-tuyen-sinh-dai-hoc-chinh-quy-nam-2026",
    )
    assert len(facts) >= 60, (
        f"Expected >=60 facts from HUST announcement HTML (pre-flight saw 68), got {len(facts)}"
    )
    for f in facts[:3]:
        assert f.program_name, "program_name must be non-empty"
        assert f.quota_raw and f.quota_raw.isdigit(), \
            f"quota_raw should be digit string, got {f.quota_raw!r}"


@pytest.mark.skipif(not FIXTURE.exists(), reason="Fixture HTML not snapshotted")
def test_method_flags_decoded():
    parser = HustAnnouncementHtmlParser()
    facts = parser.parse(
        content=FIXTURE.read_bytes(),
        source_url="https://ts.hust.edu.vn/tin-tuc/thong-tin-tuyen-sinh-dai-hoc-chinh-quy-nam-2026",
    )
    method_set = [f for f in facts if f.admission_method_raw]
    assert method_set, (
        "No facts have admission_method_raw — flag decoding from the Ö-glyph columns "
        "failed. Inspect the fixture's method-column glyphs."
    )
```

- [ ] **Step 5: Run the test**

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe -m pytest tests/ingestion/test_hust_announcement_html_parser.py -v
```

Expected: both tests PASS.

- [ ] **Step 6: Register the new parser**

Open `ingestion/parsers/base_parser.py`. Find `_auto_discover` (currently registers HUST programs, VNU-UET admission page, VNU-UET proposal PDF). Append:

```python
        try:
            from ingestion.parsers.hust_announcement_html_parser import HustAnnouncementHtmlParser
            self.register(HustAnnouncementHtmlParser())
        except ImportError as e:
            logger.warning(f"Could not load HustAnnouncementHtmlParser: {e}")
```

- [ ] **Step 7: Confirm the seed file's `parser_profile` matches the new class**

Plan 02 already wrote `parser_profile="hust_announcement_html"` into the seed file. Confirm:

```powershell
.venv/Scripts/python.exe -c "
import json
d = json.load(open('ingestion/registry/seeds/initial_sources.json', encoding='utf-8'))
for e in d:
    if e['source_id'] == 'hust_announcement_html_2026':
        print(f'parser_profile = {e[\"parser_profile\"]!r}')
        assert e['parser_profile'] == 'hust_announcement_html', 'mismatch with HustAnnouncementHtmlParser.parser_profile'
        print('OK')
"
```

If the in-DB row needs updating (the seed loader's `ON CONFLICT DO NOTHING` means existing rows are not modified by `python -m db.setup_db`):

```powershell
docker compose exec -T db psql -U postgres -d admission -c "UPDATE source_registry SET parser_profile='hust_announcement_html' WHERE source_id='hust_announcement_html_2026';"
```

---

### Task 5: Verify Parser Output Quality End-to-End

- [ ] **Step 1: Confirm parsers are registered**

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe -c "
from ingestion.parsers.base_parser import ParserRegistry
r = ParserRegistry.get_instance()
print('Registered profiles:', r.list_profiles())
assert 'hust_programs' in r.list_profiles(), 'hust_programs not registered'
print('PASS')
"
```

If you wrote the new HTML parser in Task 4, also assert `'hust_announcement_html'` is in the list.

- [ ] **Step 2: Run the diagnostic script from Task 1 again**

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe scripts/test_hust_parser.py
```

Acceptance criteria for both sources combined:
- Source #1 returns ≥10 facts (program listing; pre-flight saw 68 programs).
- Source #2 returns ≥60 facts (announcement HTML; pre-flight saw 68 rows in the table).
- ≥10 facts per source have a non-None `admission_method_raw` value.
- The Source #1 method values normalize to a canonical method code (e.g. `thpt_score`) that also appears among Source #2's method values for at least one shared program code (eyeball check: both should mention THPT, ĐGTD, or talent admission; Plan 04 makes this rigorous via the cross-source invariant test).

Note: Per the Plan 01 override (PROCEED_WITH_CAVEATS — see preflight findings), divergent quota values between Source #1 and Source #2 are NOT expected for HUST 2026 (6/6 of the listing's published quotas match the announcement exactly). The conflict signal will land on zero rows for HUST. That is the accepted outcome; Plan 05 documents it.

- [ ] **Step 3: Run all existing tests**

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe -m pytest tests/ingestion/ -v
```

Expected: all green. The HUST parser tweak in Task 2 plus the new HTML parser in Task 4 must not break VNU-UET tests.

---

### Task 6: Commit Parser Work

- [ ] **Step 1: Decide commit scope based on which tiers ran**

Stage based on what changed. Possible files:
- `scripts/test_hust_parser.py` (Tier 1 diagnostic, always)
- `ingestion/parsers/hust_program_parser.py` (Tier 2 fix, if Task 2 ran)
- `tests/ingestion/test_hust_program_parser.py` (Tier 2 test)
- `ingestion/parsers/_fixtures/hust_program_card.html` (Tier 2 fixture if added)
- `ingestion/parsers/_fixtures/hust_announcement_2026.html` (Tier 3 fixture)
- `ingestion/parsers/hust_announcement_html_parser.py` (Tier 3 parser)
- `tests/ingestion/test_hust_announcement_html_parser.py` (Tier 3 test)
- `ingestion/parsers/base_parser.py` (Tier 3 registration)

- [ ] **Step 2: Commit**

```powershell
git add scripts/test_hust_parser.py `
        ingestion/parsers/hust_program_parser.py `
        ingestion/parsers/hust_announcement_html_parser.py `
        ingestion/parsers/_fixtures/hust_announcement_2026.html `
        ingestion/parsers/base_parser.py `
        tests/ingestion/test_hust_program_parser.py `
        tests/ingestion/test_hust_announcement_html_parser.py
git commit -m "feat(ingestion): tune HUST parsers for 2026 two-source ingest

Source #1 (program listing): default method='xét điểm thi TN THPT' when
THPT subject combinations are present and no explicit method line is
recovered. Prevents canonical rows from collapsing onto admission_method
NULL when grouped with the announcement-article source.

Source #2 (announcement HTML): new HustAnnouncementHtmlParser using
BeautifulSoup4 to extract the 78-row quota table from the 2026
admission announcement article, including Ö-glyph method-flag decoding.
Plus fixture and test."
```

If Tier 1 (default profiles + LLM fallback) was sufficient for both sources, commit only the diagnostic script:

```powershell
git add scripts/test_hust_parser.py
git commit -m "docs: add HUST parser diagnostic script (default profiles sufficient)"
```

---

### Self-Check Before Proceeding to Plan 04

- `.venv/Scripts/python.exe scripts/test_hust_parser.py` produces ≥10 facts for Source #1 and ≥60 facts for Source #2
- `admission_method_raw` is non-None for ≥10 facts per source
- `.venv/Scripts/python.exe -m pytest tests/ingestion/ -v` — all green
- The VNU-UET pipeline still works: `python -m ingestion.main --school vnu_uet` returns facts without error
- If a new HTML parser was added, `parser_profile='hust_announcement_html'` is set in the seed file AND in the `source_registry` row for `hust_announcement_html_2026`
