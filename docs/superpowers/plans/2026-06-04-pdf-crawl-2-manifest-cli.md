# PDF Crawl Manifest + `crawl` CLI Implementation Plan (2/4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist crawler output into a human-reviewable `manifest.json` (merge-on-rerun so decisions survive and new PDFs surface as `pending`), and expose it as `python -m ingestion.knowledge.crawl`.

**Architecture:** New `ingestion/knowledge/crawler/manifest.py` holds the `ManifestEntry` record + load/save/merge/relevance/already-ingested logic (all pure, DI for the doc repo). A thin `ingestion/knowledge/crawl.py` CLI wires `load_targets` → `crawl_target` (plan 1) → `build_manifest` → `save_manifest`, with a printed summary.

**Tech Stack:** Python 3.12, stdlib `json`/`dataclasses`, `argparse`, existing `KnowledgeDocumentRepository`.

This is plan **2 of 4**. Depends on plan 1 (`crawl_target`, `CandidatePdf`). Output: a runnable discovery command. Consumed by plan 4 (`ingest_manifest`).

---

### Task 1: ManifestEntry + load/save round-trip

**Files:**
- Create: `ingestion/knowledge/crawler/manifest.py`
- Test: `tests/ingestion/knowledge/test_crawl_manifest.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ingestion/knowledge/test_crawl_manifest.py
from ingestion.knowledge.crawler.manifest import (
    ManifestEntry, load_manifest, save_manifest,
)


def test_save_then_load_round_trip(tmp_path):
    path = tmp_path / "manifest.json"
    entries = [
        ManifestEntry(school="HUST", url="https://a.vn/de-an.pdf",
                      anchor_text="Đề án 2026", status="keep"),
    ]
    save_manifest(path, entries)
    loaded = load_manifest(path)
    assert loaded == entries


def test_load_missing_file_returns_empty(tmp_path):
    assert load_manifest(tmp_path / "nope.json") == []


def test_save_creates_parent_dirs(tmp_path):
    path = tmp_path / "data" / "knowledge" / "manifest.json"
    save_manifest(path, [])
    assert path.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_manifest.py -q`
Expected: FAIL — `ModuleNotFoundError: ... manifest`

- [ ] **Step 3: Implement the record + load/save**

```python
# ingestion/knowledge/crawler/manifest.py
"""Review manifest for crawled PDFs: persist, merge, tag, mark-ingested.

status lifecycle: pending -> (human) keep|skip -> (ingest) done
"""
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from ingestion.knowledge.crawler.pdf_crawler import CandidatePdf

# Relevance hint only — NEVER a filter. Every PDF is listed (D4).
RELEVANCE_KEYWORDS = (
    "tuyển sinh", "tuyen sinh", "đề án", "de an", "chỉ tiêu", "chi tieu",
    "thông báo", "thong bao", "phương thức", "phuong thuc",
    "học phí", "hoc phi", "học bổng", "hoc bong",
)


@dataclass
class ManifestEntry:
    school: str
    url: str
    anchor_text: str = ""
    found_on: str = ""
    content_type: str | None = None
    size_bytes: int | None = None
    last_modified: str | None = None
    discovered_at: str = ""
    relevance: str = "low"
    status: str = "pending"
    already_ingested: bool = False


def load_manifest(path) -> list[ManifestEntry]:
    p = Path(path)
    if not p.exists():
        return []
    return [ManifestEntry(**e) for e in json.loads(p.read_text(encoding="utf-8"))]


def save_manifest(path, entries: list[ManifestEntry]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps([asdict(e) for e in entries], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_manifest.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/crawler/manifest.py tests/ingestion/knowledge/test_crawl_manifest.py
git commit -m "feat: add crawl manifest record with load/save round-trip"
```

---

### Task 2: Relevance tagging

**Files:**
- Modify: `ingestion/knowledge/crawler/manifest.py`
- Test: `tests/ingestion/knowledge/test_crawl_manifest.py` (append)

- [ ] **Step 1: Write the failing test (append)**

```python
# append to tests/ingestion/knowledge/test_crawl_manifest.py
from ingestion.knowledge.crawler.manifest import tag_relevance


def test_relevance_high_on_anchor_keyword():
    assert tag_relevance("Đề án tuyển sinh 2026", "https://a.vn/x.pdf") == "high"


def test_relevance_high_on_url_keyword_no_accent():
    assert tag_relevance("", "https://a.vn/tuyen-sinh/chi-tieu.pdf") == "high"


def test_relevance_low_when_no_keyword():
    assert tag_relevance("Quyết định nhân sự", "https://a.vn/qd-123.pdf") == "low"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_manifest.py -q`
Expected: FAIL — `ImportError: cannot import name 'tag_relevance'`

- [ ] **Step 3: Add tag_relevance**

```python
# append to ingestion/knowledge/crawler/manifest.py


def tag_relevance(anchor_text: str, url: str) -> str:
    haystack = f"{anchor_text} {url}".lower()
    return "high" if any(k in haystack for k in RELEVANCE_KEYWORDS) else "low"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_manifest.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/crawler/manifest.py tests/ingestion/knowledge/test_crawl_manifest.py
git commit -m "feat: tag crawled PDFs with relevance hint"
```

---

### Task 3: Merge candidates (preserve decisions, append new as pending)

**Files:**
- Modify: `ingestion/knowledge/crawler/manifest.py`
- Test: `tests/ingestion/knowledge/test_crawl_manifest.py` (append)

- [ ] **Step 1: Write the failing test (append)**

```python
# append to tests/ingestion/knowledge/test_crawl_manifest.py
from ingestion.knowledge.crawler.manifest import merge_candidates
from ingestion.knowledge.crawler.pdf_crawler import CandidatePdf


def test_merge_appends_new_as_pending_with_relevance():
    existing = [ManifestEntry(school="HUST", url="https://a.vn/old.pdf", status="keep")]
    cands = [CandidatePdf(school="HUST", url="https://a.vn/new.pdf",
                          anchor_text="Đề án tuyển sinh", found_on="https://a.vn/p")]
    merged = merge_candidates(existing, cands, discovered_at="2026-06-04")
    by = {m.url: m for m in merged}
    assert by["https://a.vn/old.pdf"].status == "keep"        # decision preserved
    assert by["https://a.vn/new.pdf"].status == "pending"
    assert by["https://a.vn/new.pdf"].relevance == "high"
    assert by["https://a.vn/new.pdf"].discovered_at == "2026-06-04"


def test_merge_keeps_decision_for_rediscovered_url():
    existing = [ManifestEntry(school="HUST", url="https://a.vn/x.pdf", status="skip")]
    cands = [CandidatePdf(school="HUST", url="https://a.vn/x.pdf",
                          anchor_text="x", found_on="y", size_bytes=999)]
    merged = merge_candidates(existing, cands, discovered_at="2026-06-04")
    assert len(merged) == 1
    assert merged[0].status == "skip"          # not reset to pending
    assert merged[0].size_bytes == 999         # metadata refreshed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_manifest.py -q`
Expected: FAIL — `ImportError: cannot import name 'merge_candidates'`

- [ ] **Step 3: Add merge_candidates**

```python
# append to ingestion/knowledge/crawler/manifest.py


def merge_candidates(existing: list[ManifestEntry], candidates: list[CandidatePdf],
                     *, discovered_at: str) -> list[ManifestEntry]:
    """Keep existing entries (and their human decisions); refresh metadata on
    rediscovery; append never-seen URLs as status='pending'. This is the
    anti-miss guarantee (D2): a re-crawl only ever ADDS pending work."""
    by_url: dict[str, ManifestEntry] = {e.url: e for e in existing}
    for c in candidates:
        if c.url in by_url:
            e = by_url[c.url]
            e.anchor_text = e.anchor_text or c.anchor_text
            e.content_type = c.content_type or e.content_type
            if c.size_bytes is not None:
                e.size_bytes = c.size_bytes
            e.last_modified = c.last_modified or e.last_modified
            continue
        by_url[c.url] = ManifestEntry(
            school=c.school, url=c.url, anchor_text=c.anchor_text,
            found_on=c.found_on, content_type=c.content_type,
            size_bytes=c.size_bytes, last_modified=c.last_modified,
            discovered_at=discovered_at,
            relevance=tag_relevance(c.anchor_text, c.url),
            status="pending", already_ingested=False,
        )
    return list(by_url.values())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_manifest.py -q`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/crawler/manifest.py tests/ingestion/knowledge/test_crawl_manifest.py
git commit -m "feat: merge crawl candidates preserving review decisions"
```

---

### Task 4: Mark already-ingested (DI doc repo)

**Files:**
- Modify: `ingestion/knowledge/crawler/manifest.py`
- Test: `tests/ingestion/knowledge/test_crawl_manifest.py` (append)

- [ ] **Step 1: Write the failing test (append)**

```python
# append to tests/ingestion/knowledge/test_crawl_manifest.py
from ingestion.knowledge.crawler.manifest import mark_already_ingested


class _FakeDocRepo:
    def __init__(self, known_urls):
        self._known = set(known_urls)

    def get_document_by_url(self, url):
        return object() if url in self._known else None


def test_mark_already_ingested_sets_flag():
    entries = [
        ManifestEntry(school="HUST", url="https://a.vn/seen.pdf"),
        ManifestEntry(school="HUST", url="https://a.vn/fresh.pdf"),
    ]
    mark_already_ingested(entries, _FakeDocRepo({"https://a.vn/seen.pdf"}))
    flags = {e.url: e.already_ingested for e in entries}
    assert flags == {"https://a.vn/seen.pdf": True, "https://a.vn/fresh.pdf": False}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_manifest.py -q`
Expected: FAIL — `ImportError: cannot import name 'mark_already_ingested'`

- [ ] **Step 3: Add mark_already_ingested**

```python
# append to ingestion/knowledge/crawler/manifest.py


def mark_already_ingested(entries: list[ManifestEntry], doc_repo) -> list[ManifestEntry]:
    """Set already_ingested by checking the knowledge_documents store by URL."""
    for e in entries:
        e.already_ingested = doc_repo.get_document_by_url(e.url) is not None
    return entries
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_manifest.py -q`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/crawler/manifest.py tests/ingestion/knowledge/test_crawl_manifest.py
git commit -m "feat: flag manifest entries already in the knowledge store"
```

---

### Task 5: `build_manifest` orchestrator + `crawl` CLI

**Files:**
- Create: `ingestion/knowledge/crawl.py`
- Test: `tests/ingestion/knowledge/test_crawl_cli.py`

- [ ] **Step 1: Write the failing test (test the pure orchestrator, not argparse)**

```python
# tests/ingestion/knowledge/test_crawl_cli.py
from ingestion.knowledge.crawl import build_manifest
from ingestion.knowledge.crawler.config import CrawlTarget
from ingestion.knowledge.crawler.manifest import ManifestEntry
from ingestion.knowledge.crawler.pdf_crawler import CandidatePdf


class _FakeDocRepo:
    def get_document_by_url(self, url):
        return None


def test_build_manifest_merges_crawl_output():
    targets = [CrawlTarget(school="HUST", seeds=["https://a.vn/s"],
                           allow_domains=["a.vn"])]

    def fake_crawl(target, sitemap=True):
        return [CandidatePdf(school="HUST", url="https://a.vn/de-an.pdf",
                             anchor_text="Đề án tuyển sinh", found_on="https://a.vn/s")]

    merged = build_manifest(targets, existing=[], crawl=fake_crawl,
                            doc_repo=_FakeDocRepo(), discovered_at="2026-06-04")
    assert len(merged) == 1
    assert merged[0].status == "pending"
    assert merged[0].relevance == "high"


def test_build_manifest_isolates_failing_target():
    targets = [
        CrawlTarget(school="HUST", seeds=["https://a.vn/s"], allow_domains=["a.vn"]),
        CrawlTarget(school="NEU", seeds=["https://b.vn/s"], allow_domains=["b.vn"]),
    ]

    def fake_crawl(target, sitemap=True):
        if target.school == "HUST":
            raise RuntimeError("boom")
        return [CandidatePdf(school="NEU", url="https://b.vn/x.pdf",
                             anchor_text="x", found_on="https://b.vn/s")]

    merged = build_manifest(targets, existing=[], crawl=fake_crawl,
                            doc_repo=_FakeDocRepo(), discovered_at="2026-06-04")
    assert {m.url for m in merged} == {"https://b.vn/x.pdf"}  # NEU survived HUST failure


def test_build_manifest_preserves_existing_decisions():
    targets = [CrawlTarget(school="HUST", seeds=["https://a.vn/s"], allow_domains=["a.vn"])]
    existing = [ManifestEntry(school="HUST", url="https://a.vn/de-an.pdf", status="skip")]

    def fake_crawl(target, sitemap=True):
        return [CandidatePdf(school="HUST", url="https://a.vn/de-an.pdf",
                             anchor_text="x", found_on="https://a.vn/s")]

    merged = build_manifest(targets, existing=existing, crawl=fake_crawl,
                            doc_repo=_FakeDocRepo(), discovered_at="2026-06-04")
    assert merged[0].status == "skip"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_cli.py -q`
Expected: FAIL — `ModuleNotFoundError: ... ingestion.knowledge.crawl`

- [ ] **Step 3: Implement build_manifest + the CLI glue**

```python
# ingestion/knowledge/crawl.py
"""CLI: discover PDFs per school into a reviewable manifest.

    python -m ingestion.knowledge.crawl --school HUST
    python -m ingestion.knowledge.crawl --all
Then edit data/knowledge/manifest.json (set status keep/skip) and run
`python -m ingestion.knowledge.ingest_manifest` (plan 4).
"""
import logging
from pathlib import Path

from ingestion.knowledge.crawler.config import load_targets
from ingestion.knowledge.crawler.manifest import (
    load_manifest, mark_already_ingested, merge_candidates, save_manifest,
)
from ingestion.knowledge.crawler.pdf_crawler import crawl_target

logger = logging.getLogger(__name__)

DEFAULT_MANIFEST = Path("data/knowledge/manifest.json")


def build_manifest(targets, existing, *, crawl, doc_repo, discovered_at,
                   sitemap=True):
    """Crawl every target (one failure never aborts the rest), merge into the
    existing manifest, and flag already-ingested URLs."""
    candidates = []
    for t in targets:
        try:
            candidates.extend(crawl(t, sitemap=sitemap))
        except Exception as exc:  # one bad target must not abort the run
            logger.error("crawl failed for %s: %r", t.school, exc)
    merged = merge_candidates(existing, candidates, discovered_at=discovered_at)
    mark_already_ingested(merged, doc_repo)
    return merged


def _main(argv=None) -> int:
    import argparse
    from datetime import date

    from services.knowledge.repository import KnowledgeDocumentRepository

    parser = argparse.ArgumentParser(description="Discover admission PDFs into a manifest")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--school", help="crawl one school, e.g. HUST")
    group.add_argument("--all", action="store_true", help="crawl all configured schools")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--no-sitemap", action="store_true",
                        help="skip sitemap.xml discovery")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    targets = load_targets()
    if args.school:
        targets = [t for t in targets if t.school == args.school]
        if not targets:
            parser.error(f"no crawl target configured for school {args.school!r}")

    existing = load_manifest(args.manifest)
    merged = build_manifest(
        targets, existing, crawl=crawl_target,
        doc_repo=KnowledgeDocumentRepository(),
        discovered_at=date.today().isoformat(), sitemap=not args.no_sitemap,
    )
    save_manifest(args.manifest, merged)

    new_count = len(merged) - len(existing)
    pending = sum(1 for e in merged if e.status == "pending")
    already = sum(1 for e in merged if e.already_ingested)
    print(f"Manifest: {args.manifest}")
    print(f"  total={len(merged)}  new={new_count}  pending={pending}  "
          f"already_ingested={already}")
    print("Review the manifest (set status keep/skip), then run "
          "`python -m ingestion.knowledge.ingest_manifest`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_cli.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/crawl.py tests/ingestion/knowledge/test_crawl_cli.py
git commit -m "feat: add crawl CLI building reviewable PDF manifest"
```

---

## Done when
- `python -m ingestion.knowledge.crawl --school HUST` writes/merges `data/knowledge/manifest.json` and prints a `total/new/pending/already_ingested` summary.
- Re-running never resets a human `keep`/`skip`; new PDFs appear as `pending`.
- `build_manifest` is unit-tested offline (fake crawl + fake doc repo), including per-target failure isolation.
- Next: plan 3 adds the hybrid ingest-by-URL path the manifest will feed.
