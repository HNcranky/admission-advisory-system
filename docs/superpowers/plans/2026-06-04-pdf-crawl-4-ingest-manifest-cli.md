# PDF `ingest_manifest` CLI Implementation Plan (4/4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the loop — `python -m ingestion.knowledge.ingest_manifest` reads the reviewed manifest, ingests every `status=keep` entry via `run_for_url` (plan 3), and writes back `done` (success/skip) or leaves `keep` (failure, so it retries next run).

**Architecture:** A pure `ingest_keep_entries(entries, pipe)` orchestrator (mutates entry status, returns per-URL labels) keeps the logic unit-testable with a fake pipeline. A thin `_main` wires `load_manifest` → real `KnowledgePipeline` → `ingest_keep_entries` → `save_manifest` + summary.

**Tech Stack:** Python 3.12, `argparse`, plans 2–3 (`ManifestEntry`/load/save, `KnowledgePipeline.run_for_url`).

This is plan **4 of 4**. Depends on plan 2 (manifest) and plan 3 (`run_for_url`).

---

### Task 1: `ingest_keep_entries` orchestrator

**Files:**
- Create: `ingestion/knowledge/ingest_manifest.py`
- Test: `tests/ingestion/knowledge/test_ingest_manifest.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ingestion/knowledge/test_ingest_manifest.py
from ingestion.knowledge.crawler.manifest import ManifestEntry
from ingestion.knowledge.ingest_manifest import ingest_keep_entries
from ingestion.knowledge.pipeline import KnowledgeIngestResult


class FakePipe:
    def __init__(self, behavior):
        self.behavior = behavior          # url -> KnowledgeIngestResult | Exception
        self.calls = []

    def run_for_url(self, url, *, school, **kwargs):
        self.calls.append((url, school))
        outcome = self.behavior[url]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _entry(url, school="HUST", status="keep"):
    return ManifestEntry(school=school, url=url, status=status)


def _ok(url):
    return KnowledgeIngestResult(source_url=url, skipped=False)


def _skip(url):
    return KnowledgeIngestResult(source_url=url, skipped=True)


def test_only_keep_entries_are_ingested():
    entries = [
        _entry("https://a.vn/keep.pdf", status="keep"),
        _entry("https://a.vn/skip.pdf", status="skip"),
        _entry("https://a.vn/pending.pdf", status="pending"),
        _entry("https://a.vn/done.pdf", status="done"),
    ]
    pipe = FakePipe({"https://a.vn/keep.pdf": _ok("https://a.vn/keep.pdf")})
    ingest_keep_entries(entries, pipe)
    assert [u for u, _ in pipe.calls] == ["https://a.vn/keep.pdf"]


def test_success_sets_done_and_passes_entry_school():
    entries = [_entry("https://a.vn/k.pdf", school="NEU", status="keep")]
    pipe = FakePipe({"https://a.vn/k.pdf": _ok("https://a.vn/k.pdf")})
    results = ingest_keep_entries(entries, pipe)
    assert entries[0].status == "done"
    assert pipe.calls == [("https://a.vn/k.pdf", "NEU")]
    assert results == [("OK", "https://a.vn/k.pdf")]


def test_skip_unchanged_also_marks_done():
    entries = [_entry("https://a.vn/k.pdf", status="keep")]
    pipe = FakePipe({"https://a.vn/k.pdf": _skip("https://a.vn/k.pdf")})
    results = ingest_keep_entries(entries, pipe)
    assert entries[0].status == "done"
    assert results == [("SKIP", "https://a.vn/k.pdf")]


def test_failure_keeps_status_for_retry():
    entries = [_entry("https://a.vn/bad.pdf", status="keep")]
    pipe = FakePipe({"https://a.vn/bad.pdf": RuntimeError("boom")})
    results = ingest_keep_entries(entries, pipe)
    assert entries[0].status == "keep"        # not done → retried next run
    assert results == [("FAIL", "https://a.vn/bad.pdf")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_ingest_manifest.py -q`
Expected: FAIL — `ModuleNotFoundError: ... ingest_manifest`

- [ ] **Step 3: Implement the orchestrator**

```python
# ingestion/knowledge/ingest_manifest.py
"""CLI: ingest the PDFs you marked status=keep in the crawl manifest.

    python -m ingestion.knowledge.ingest_manifest
Each kept URL is ingested via KnowledgePipeline.run_for_url (hybrid OCR);
on success/skip its status becomes 'done', on failure it stays 'keep' to retry.
"""
import logging

logger = logging.getLogger(__name__)


def ingest_keep_entries(entries, pipe):
    """Ingest every status=='keep' entry through `pipe.run_for_url`.
    Mutates each entry's status; returns [(label, url)] where label is
    OK / SKIP / FAIL. One failure never aborts the rest."""
    results = []
    for e in entries:
        if e.status != "keep":
            continue
        try:
            result = pipe.run_for_url(e.url, school=e.school)
        except Exception as exc:  # one bad URL must not abort the batch
            logger.error("ingest failed %s: %r", e.url, exc)
            results.append(("FAIL", e.url))
            continue
        e.status = "done"
        results.append(("SKIP" if result.skipped else "OK", e.url))
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_ingest_manifest.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/ingest_manifest.py tests/ingestion/knowledge/test_ingest_manifest.py
git commit -m "feat: ingest kept manifest entries via run_for_url"
```

---

### Task 2: `_main` CLI glue + summary

**Files:**
- Modify: `ingestion/knowledge/ingest_manifest.py`
- Test: `tests/ingestion/knowledge/test_ingest_manifest.py` (append)

- [ ] **Step 1: Write the failing test (append)**

```python
# append to tests/ingestion/knowledge/test_ingest_manifest.py
import ingestion.knowledge.ingest_manifest as mod
from ingestion.knowledge.crawler.manifest import load_manifest, save_manifest


def test_main_ingests_keep_and_persists_status(tmp_path, monkeypatch, capsys):
    path = tmp_path / "manifest.json"
    save_manifest(path, [
        ManifestEntry(school="HUST", url="https://a.vn/k.pdf", status="keep"),
        ManifestEntry(school="HUST", url="https://a.vn/s.pdf", status="skip"),
    ])

    class FakePipeline:
        def run_for_url(self, url, *, school, **kwargs):
            return KnowledgeIngestResult(source_url=url, skipped=False)

    monkeypatch.setattr(mod, "KnowledgePipeline", lambda: FakePipeline())

    rc = mod._main(["--manifest", str(path)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "https://a.vn/k.pdf" in out
    assert "ok=1" in out
    after = {e.url: e.status for e in load_manifest(path)}
    assert after == {"https://a.vn/k.pdf": "done", "https://a.vn/s.pdf": "skip"}


def test_main_no_keep_entries_is_a_noop(tmp_path, monkeypatch, capsys):
    path = tmp_path / "manifest.json"
    save_manifest(path, [ManifestEntry(school="HUST", url="https://a.vn/p.pdf",
                                       status="pending")])

    def _boom():
        raise AssertionError("pipeline must not be built when nothing is kept")

    monkeypatch.setattr(mod, "KnowledgePipeline", _boom)

    rc = mod._main(["--manifest", str(path)])

    assert rc == 0
    assert "No entries with status=keep" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_ingest_manifest.py -q`
Expected: FAIL — `AttributeError: module 'ingestion.knowledge.ingest_manifest' has no attribute '_main'`

- [ ] **Step 3: Add `_main` (and the imports it needs)**

Add these imports near the top of `ingestion/knowledge/ingest_manifest.py` (below the existing `import logging`):

```python
from ingestion.knowledge.crawl import DEFAULT_MANIFEST
from ingestion.knowledge.crawler.manifest import load_manifest, save_manifest
from ingestion.knowledge.pipeline import KnowledgePipeline
```

Append the CLI entry point at the end of the module:

```python
def _main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Ingest PDFs marked status=keep in the crawl manifest"
    )
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    entries = load_manifest(args.manifest)
    if not any(e.status == "keep" for e in entries):
        print(f"No entries with status=keep in {args.manifest}. "
              "Edit the manifest (set status=keep) first.")
        return 0

    results = ingest_keep_entries(entries, KnowledgePipeline())
    save_manifest(args.manifest, entries)

    for label, url in results:
        print(f"{label:<5} {url}")
    ok = sum(1 for s, _ in results if s == "OK")
    skipped = sum(1 for s, _ in results if s == "SKIP")
    failed = sum(1 for s, _ in results if s == "FAIL")
    print(f"Done: {len(results)} processed (ok={ok} skip={skipped} fail={failed})")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_ingest_manifest.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/ingest_manifest.py tests/ingestion/knowledge/test_ingest_manifest.py
git commit -m "feat: add ingest_manifest CLI with done/keep status writeback"
```

---

### Task 3: Manual end-to-end verification (needs Docker DB + Gemini key)

Not a unit test — this exercises the full discover → review → ingest loop against the real DB and Gemini, the way the `verify` skill drove the local flow.

- [ ] **Step 1: Bring up the DB**

Run: `docker compose up -d --wait db` (or `docker start advisory-db` if the container already exists)
Expected: container healthy on `localhost:5432`.

- [ ] **Step 2: Confirm `pymupdf` is installed (OCR renderer)**

Run: `.venv/bin/python -c "import pymupdf; print(pymupdf.__version__)"`
Expected: prints a version. If `ModuleNotFoundError`, run `.venv/bin/python -m pip install -r requirements.txt`.

- [ ] **Step 3: Crawl one school into the manifest**

Run:
```bash
set -a; source .env; set +a
.venv/bin/python -m ingestion.knowledge.crawl --school HUST
```
Expected: `data/knowledge/manifest.json` created; summary prints `total/new/pending/already_ingested`. Open the file and confirm entries have real PDF URLs + `relevance` tags.

- [ ] **Step 4: Review — mark a couple entries keep**

Edit `data/knowledge/manifest.json`: set `"status": "keep"` on 1–2 high-relevance PDFs (leave the rest `pending`).

- [ ] **Step 5: Ingest the kept entries**

Run:
```bash
set -a; source .env; set +a
.venv/bin/python -m ingestion.knowledge.ingest_manifest
```
Expected: `OK`/`SKIP` lines per kept URL + `Done: N processed (...)`. Kept entries flip to `"status": "done"` in the manifest.

- [ ] **Step 6: Confirm rows landed (citation = school URL)**

Run:
```bash
docker exec advisory-db psql -U postgres -d admission -x -c \
 "select school, document_type, source_url, length(raw_text) raw_len from knowledge_documents where document_type='crawled_pdf' order by id desc limit 3;"
```
Expected: rows with `document_type=crawled_pdf`, `source_url` = the `https://...` school URL, non-zero `raw_len`.

- [ ] **Step 7: Re-run ingest to confirm idempotency**

Run: `.venv/bin/python -m ingestion.knowledge.ingest_manifest`
Expected: `No entries with status=keep` (everything is `done`) — re-running is a no-op. (If you re-`keep` a done entry, it should print `SKIP` via the content-hash check.)

---

## Done when
- `crawl` → edit manifest → `ingest_manifest` ingests kept PDFs end-to-end; citations point to the school URLs; re-runs are idempotent.
- `ingest_keep_entries` is unit-tested (keep-only, done-on-success, keep-on-failure, skip-marks-done) and `_main` round-trips status to disk.
- Full suite green: `.venv/bin/python -m pytest tests/ingestion/knowledge -q`.
