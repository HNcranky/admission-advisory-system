# NEU / VNU-UET Program-Overview Seeds — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Onboard NEU and VNU-UET program-overview pages into the knowledge corpus using the generalized mechanism (seed-supplied canonical `program`, `by_section` chunking that degrades to size-split, query-time program filter), then verify retrieval returns the right program's section on pages that lack HUST's `<h2>` structure.

**Architecture:** This plan adds data + config, not code. For each school it (1) discovers program-overview URLs and the content CSS selector by inspecting the live site (mirroring the HUST scrape/inspect scripts), (2) appends seed entries with an explicit canonical `program` and `chunk_strategy: by_section`, (3) re-ingests, (4) spot-checks that a program-named sub-topic query resolves and filters correctly.

**Tech Stack:** Python 3.12, requests/BeautifulSoup probe scripts, Postgres, pytest.

This is **Plan 3 of 3** and **depends on Plan 1** (program filter at retrieval) **and Plan 2** (seed-first program metadata). Implement those first — without Plan 2, a seed's `program` is ignored for `by_section`; without Plan 1, the filter never applies.

## Global Constraints

- **Never run `git push`.** Commit only; **no `Co-Authored-By` trailer or any AI/Claude attribution** in commit messages.
- `scripts/` holds one-off probes — NOT part of the test suite; some fetch the network at import.
- **SSL verification is OFF by default** (`ADVISORY_FETCH_VERIFY_SSL`); several official sources have broken certs. Expect and log per-fetch SSL skips.
- Seeds must validate against `KnowledgeSource` (`ingestion/knowledge/registry/models.py`): `topic` ∈ taxonomy, `document_type` ∈ taxonomy.
- **Convention (from the spec):** a seed's `program` is the program's **canonical catalog name**, so it matches `resolve_program` results and the canonical store.
- Run tests with system Python: `python -m pytest -q`.
- Re-ingest commands need the Docker DB up: `docker compose up -d --wait db`.

---

## File Structure

- `scripts/scrape_neu_program_urls.py` — **create** (probe; models `scripts/scrape_hust_program_urls.py`).
- `scripts/neu_program_urls.txt`, `scripts/vnu_uet_program_urls.txt` — **create** (discovered URL lists).
- `ingestion/knowledge/registry/seeds/knowledge_sources.json` — **modify** (append NEU + VNU-UET `program_overview` entries).
- `tests/ingestion/knowledge/test_program_overview_seeds.py` — **create** (seed-shape invariant).

---

### Task 1: Discover NEU program-overview URLs + content selector

**Files:**
- Create: `scripts/scrape_neu_program_urls.py`, `scripts/neu_program_urls.txt`

**Interfaces:**
- Produces: a newline-delimited list of NEU program-overview page URLs, and a verified CSS `selector` string that isolates the program content container (analogous to HUST's `div.container:nth-child(2)`).

- [ ] **Step 1: Inspect the NEU program listing page**

NEU's program catalog lives under the admissions site (e.g. `https://daotao.neu.edu.vn` / `https://tuyensinh.neu.edu.vn`). Open the program-listing page in a browser and identify: (a) the per-program detail URL pattern, (b) the DOM container holding the overview prose.

- [ ] **Step 2: Write the URL scraper (model on the HUST one)**

Read `scripts/scrape_hust_program_urls.py` first and copy its structure. `scripts/scrape_neu_program_urls.py` should: fetch the listing page with `ingestion.fetchers.http_fetcher.http_fetch` (so SSL-off + UA rotation apply), collect program-detail hrefs, and print them one per line.

- [ ] **Step 3: Run the scraper and save the list**

Run: `python scripts/scrape_neu_program_urls.py > scripts/neu_program_urls.txt`
Expected: a non-empty file of absolute NEU program URLs. Eyeball for obvious non-program links (news, login) and delete them.

- [ ] **Step 4: Verify the content selector on a sample page**

Read `scripts/test_vnu_uet_parser.py` for the parser-probe pattern, then probe one NEU URL: call `parse_html(raw, url, selector="<candidate>")` and confirm `.text` is the program overview (not nav) and `.content_label` is the program name. Iterate the selector until both are clean.

- [ ] **Step 5: Record findings**

At the top of `scripts/neu_program_urls.txt`, add a comment line with the verified selector, e.g. `# selector: <div...>`. (No automated test — this is discovery output consumed by Task 3.)

- [ ] **Step 6: Commit**

```bash
git add scripts/scrape_neu_program_urls.py scripts/neu_program_urls.txt
git commit -m "chore(knowledge): NEU program-overview URL scraper + discovered URLs"
```

---

### Task 2: Discover VNU-UET program-overview URLs + content selector

**Files:**
- Create: `scripts/vnu_uet_program_urls.txt`

**Interfaces:**
- Produces: VNU-UET program-overview URLs + a verified selector. (A scraper script is optional; if the listing is small, hand-curate the list.)

- [ ] **Step 1: Inspect the VNU-UET program listing**

VNU-UET program pages live under `https://uet.vnu.edu.vn` / `https://tuyensinh.uet.vnu.edu.vn`. Use `scripts/test_vnu_uet_parser.py` (already exists) as the probe to confirm the content selector and that `content_label` yields the program name.

- [ ] **Step 2: Collect URLs into `scripts/vnu_uet_program_urls.txt`**

One URL per line; first line a `# selector: ...` comment. Hand-curate or extend the NEU scraper if a listing page exists.

- [ ] **Step 3: Verify one page parses cleanly**

Run: `python scripts/test_vnu_uet_parser.py` (adjust to point at a program URL + your selector)
Expected: prints non-empty overview text and a sensible `content_label`.

- [ ] **Step 4: Commit**

```bash
git add scripts/vnu_uet_program_urls.txt
git commit -m "chore(knowledge): VNU-UET program-overview URLs + selector"
```

---

### Task 3: Add NEU + VNU-UET program_overview seeds

**Files:**
- Modify: `ingestion/knowledge/registry/seeds/knowledge_sources.json`
- Test: `tests/ingestion/knowledge/test_program_overview_seeds.py`

**Interfaces:**
- Consumes: URL lists + selectors (Tasks 1-2); seed-first `program` wiring (Plan 2).
- Produces: seed entries shaped like the HUST `program_overview` entries **plus** an explicit canonical `program`.

- [ ] **Step 1: Write the failing invariant test**

`tests/ingestion/knowledge/test_program_overview_seeds.py`:

```python
import json
from pathlib import Path

from ingestion.knowledge.registry.models import KnowledgeSource

SEEDS = (Path(__file__).resolve().parents[3]
         / "ingestion/knowledge/registry/seeds/knowledge_sources.json")


def _load():
    raw = json.loads(SEEDS.read_text(encoding="utf-8"))
    return [KnowledgeSource(**d) for d in raw]


def test_all_seeds_validate():
    # KnowledgeSource(**d) raises on a bad topic/document_type.
    assert _load(), "seed file empty or unparseable"


def test_new_school_program_overview_seeds_have_canonical_program():
    srcs = _load()
    new = [s for s in srcs
           if s.topic == "program_overview" and s.school in ("NEU", "VNU-UET")]
    assert new, "expected NEU/VNU-UET program_overview seeds"
    for s in new:
        assert s.program and s.program.strip(), \
            f"{s.source_url}: program_overview seed must set canonical program"
        assert s.chunk_strategy == "by_section", \
            f"{s.source_url}: program_overview must use by_section"
        assert s.document_type == "program_overview_page", s.source_url
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/ingestion/knowledge/test_program_overview_seeds.py -v`
Expected: `test_new_school_program_overview_seeds_have_canonical_program` FAILS with "expected NEU/VNU-UET program_overview seeds" (none exist yet).

- [ ] **Step 3: Append the seed entries**

For each discovered URL, append an object to `ingestion/knowledge/registry/seeds/knowledge_sources.json`. Template (one per program; `program` = canonical catalog name, `selector` = the verified selector for that school):

```json
  {
    "school": "NEU",
    "source_url": "https://<neu-program-url>",
    "document_type": "program_overview_page",
    "topic": "program_overview",
    "fetch_strategy": "http",
    "selector": "<neu-content-selector>",
    "year": 2026,
    "chunk_strategy": "by_section",
    "program": "Khoa học Máy tính"
  }
```

Repeat with `"school": "VNU-UET"` and that school's selector for the VNU-UET URLs. Ensure the JSON stays valid (commas between objects, no trailing comma).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/ingestion/knowledge/test_program_overview_seeds.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/registry/seeds/knowledge_sources.json tests/ingestion/knowledge/test_program_overview_seeds.py
git commit -m "feat(knowledge): NEU + VNU-UET program-overview seeds with canonical program"
```

---

### Task 4: Re-ingest and verify retrieval on unstructured pages

**Files:** none (rollout + verification)

**Interfaces:**
- Consumes: Plans 1-2 merged + Task 3 seeds.

- [ ] **Step 1: Bring up the DB and re-ingest the new schools**

Run:
```bash
docker compose up -d --wait db
python -m ingestion.main --school NEU
python -m ingestion.main --school VNU-UET
```
Expected: per-source "Ingested … N chunks" logs; SSL-skip warnings are expected and fine.

- [ ] **Step 2: Confirm chunks carry the canonical program**

Run:
```bash
python -c "from services.knowledge.repository import KnowledgeChunkRepository as R; import collections; rows=R().search_by_metadata('NEU', topic='program_overview', limit=200); print(collections.Counter(c.program for c in rows))"
```
Expected: a Counter keyed by canonical program names (not `None`, not raw slugs). Repeat with `'VNU-UET'`.

- [ ] **Step 3: Confirm program resolution works on a free-prose page**

Pick one NEU program known to lack `<h2>` structure. Run:
```bash
python -c "from services.knowledge.repository import KnowledgeChunkRepository as R; print(R().resolve_program('chương trình ngành <PROGRAM> học những gì', 'NEU'))"
```
Expected: prints the canonical program name (resolution does not depend on page structure).

- [ ] **Step 4: Spot-check end-to-end retrieval**

Ask a program-named sub-topic question for NEU/VNU-UET through the QA path (web UI or a small driver calling `KnowledgeQAService().retrieve(question, school, "program_overview")`). Confirm the returned chunks belong to the named program.

- [ ] **Step 5: Confirm a policy question is unaffected**

Ask a school-level admission_policy question (no program named). Confirm `resolve_program` returns `None` for it and retrieval is unchanged (regression guard for the soft-filter contract).

- [ ] **Step 6: Record the rollout outcome**

Note in the PR/commit description: schools ingested, chunk counts, and the spot-check result. No code change to commit unless a selector/seed needed a fix (then amend Task 3's commit scope).

---

## Self-Review Notes (coverage map & risks)

- Spec §1 (seed program canonical) → Task 3 test + template. Spec §2 (`by_section` on any school) → Tasks 1-3 selectors + Task 4 Step 3 (free-prose resolution). Spec §3 (filter) exercised in Task 4 Step 4. Spec §5 edge case (policy = no-op) → Task 4 Step 5.
- **Risk:** URLs/selectors are live-site dependent and may drift; Tasks 1-2 are discovery, so their "tests" are manual probes, not pytest. The only automated guard is the seed-shape invariant (Task 3).
- **Risk:** if a school's pages DO have `<h2>` structure, `by_section` sections them (better); if not, it size-splits — either way the canonical `program` filter carries identity. No code branch needed.
- No placeholder code: the JSON template and probe steps are concrete; program names in examples are illustrative and replaced with real canonical names during Task 3.
