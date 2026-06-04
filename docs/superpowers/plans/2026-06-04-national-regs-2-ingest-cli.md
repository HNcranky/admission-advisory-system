# National Regulations — Plan 2/3: `ingest_national` CLI

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `python -m ingestion.knowledge.ingest_national` CLI that ingests every curated national-regulation PDF under the `MOET` scope via the existing hybrid (text+OCR) URL pipeline, isolating per-URL failures and printing an OK/SKIP/FAIL summary.

**Architecture:** Mirror `ingestion/knowledge/ingest_manifest.py`. A testable core `ingest_sources(sources, pipe)` loops the curated rows and calls `pipe.run_for_url(url, school=NATIONAL_SCHOOL, document_type=NATIONAL_DOCUMENT_TYPE)`; `run_for_url` is reused unchanged (fetch → `extract_pages_hybrid` → chunk/embed/upsert → `mark_ingested`, idempotent via `content_hash`). `_main` wires the loader + a real `KnowledgePipeline`.

**Tech Stack:** Python 3.12, `argparse`, pytest, dependency injection (fake pipe).

**Depends on Plan 1** (`services.knowledge.scope`, `load_national_sources`). Implements spec §5.3 and §7.

---

### Task 1: `ingest_sources` core (error-isolated batch)

**Files:**
- Create: `ingestion/knowledge/ingest_national.py`
- Test: `tests/ingestion/knowledge/test_ingest_national.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ingestion/knowledge/test_ingest_national.py
import ingestion.knowledge.ingest_national as mod
from ingestion.knowledge.ingest_national import ingest_sources
from ingestion.knowledge.pipeline import KnowledgeIngestResult
from services.knowledge.scope import NATIONAL_SCHOOL, NATIONAL_DOCUMENT_TYPE


class FakePipe:
    def __init__(self, behavior):
        self.behavior = behavior          # url -> KnowledgeIngestResult | Exception
        self.calls = []

    def run_for_url(self, url, *, school, document_type=None, **kwargs):
        self.calls.append((url, school, document_type))
        outcome = self.behavior[url]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _ok(url):
    return KnowledgeIngestResult(source_url=url, skipped=False)


def _skip(url):
    return KnowledgeIngestResult(source_url=url, skipped=True)


def test_ingests_each_source_under_national_scope():
    sources = [{"url": "https://cp/a.pdf", "title": "A"},
               {"url": "https://cp/b.pdf", "title": "B"}]
    pipe = FakePipe({"https://cp/a.pdf": _ok("https://cp/a.pdf"),
                     "https://cp/b.pdf": _ok("https://cp/b.pdf")})
    results = ingest_sources(sources, pipe)
    assert pipe.calls == [
        ("https://cp/a.pdf", NATIONAL_SCHOOL, NATIONAL_DOCUMENT_TYPE),
        ("https://cp/b.pdf", NATIONAL_SCHOOL, NATIONAL_DOCUMENT_TYPE),
    ]
    assert results == [("OK", "https://cp/a.pdf"), ("OK", "https://cp/b.pdf")]


def test_unchanged_source_is_reported_skip():
    sources = [{"url": "https://cp/a.pdf", "title": "A"}]
    pipe = FakePipe({"https://cp/a.pdf": _skip("https://cp/a.pdf")})
    assert ingest_sources(sources, pipe) == [("SKIP", "https://cp/a.pdf")]


def test_one_failure_does_not_abort_the_batch():
    sources = [{"url": "https://cp/a.pdf", "title": "A"},
               {"url": "https://cp/bad.pdf", "title": "bad"},
               {"url": "https://cp/c.pdf", "title": "C"}]
    pipe = FakePipe({"https://cp/a.pdf": _ok("https://cp/a.pdf"),
                     "https://cp/bad.pdf": RuntimeError("boom"),
                     "https://cp/c.pdf": _ok("https://cp/c.pdf")})
    results = ingest_sources(sources, pipe)
    assert results == [("OK", "https://cp/a.pdf"),
                       ("FAIL", "https://cp/bad.pdf"),
                       ("OK", "https://cp/c.pdf")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_ingest_national.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingestion.knowledge.ingest_national'`

- [ ] **Step 3: Implement `ingest_sources`**

```python
# ingestion/knowledge/ingest_national.py
"""CLI: ingest the curated official national admission regulations.

    python -m ingestion.knowledge.ingest_national
Each curated URL (datafiles.chinhphu.vn signed PDF) is ingested via
KnowledgePipeline.run_for_url under the national scope (school="MOET",
document_type="national_regulation"). Idempotent: unchanged URLs skip
on content_hash. One bad URL never aborts the rest."""
import logging

from ingestion.knowledge.national_sources import load_national_sources
from ingestion.knowledge.pipeline import KnowledgePipeline
from services.knowledge.scope import NATIONAL_DOCUMENT_TYPE, NATIONAL_SCHOOL

logger = logging.getLogger(__name__)


def ingest_sources(sources, pipe):
    """Ingest every curated row via `pipe.run_for_url` under the national scope.
    Returns [(label, url)] where label is OK / SKIP / FAIL. One failure never
    aborts the rest."""
    results = []
    for s in sources:
        url = s["url"]
        try:
            result = pipe.run_for_url(
                url, school=NATIONAL_SCHOOL, document_type=NATIONAL_DOCUMENT_TYPE
            )
        except Exception as exc:  # one bad URL must not abort the batch
            logger.error("national ingest failed %s: %r", url, exc)
            results.append(("FAIL", url))
            continue
        results.append(("SKIP" if result.skipped else "OK", url))
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_ingest_national.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/ingest_national.py tests/ingestion/knowledge/test_ingest_national.py
git commit -m "feat: add ingest_sources core for national regulations"
```

---

### Task 2: `_main` CLI wiring

**Files:**
- Modify: `ingestion/knowledge/ingest_national.py`
- Test: `tests/ingestion/knowledge/test_ingest_national.py` (append)

- [ ] **Step 1: Write the failing test (append)**

```python
# append to tests/ingestion/knowledge/test_ingest_national.py
def test_main_ingests_sources_and_prints_summary(monkeypatch, capsys):
    monkeypatch.setattr(mod, "load_national_sources",
                        lambda path=None: [{"url": "https://cp/a.pdf", "title": "A"}])

    class FakePipeline:
        def run_for_url(self, url, *, school, document_type=None, **kwargs):
            return KnowledgeIngestResult(source_url=url, skipped=False)

    monkeypatch.setattr(mod, "KnowledgePipeline", lambda: FakePipeline())

    rc = mod._main([])

    out = capsys.readouterr().out
    assert rc == 0
    assert "https://cp/a.pdf" in out
    assert "ok=1" in out


def test_main_no_sources_is_a_noop(monkeypatch, capsys):
    monkeypatch.setattr(mod, "load_national_sources", lambda path=None: [])

    def _boom():
        raise AssertionError("pipeline must not be built when there are no sources")

    monkeypatch.setattr(mod, "KnowledgePipeline", _boom)

    rc = mod._main([])

    assert rc == 0
    assert "No national sources" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_ingest_national.py::test_main_ingests_sources_and_prints_summary -q`
Expected: FAIL — `AttributeError: module 'ingestion.knowledge.ingest_national' has no attribute '_main'`

- [ ] **Step 3: Add `_main` and the module entrypoint**

Append to `ingestion/knowledge/ingest_national.py`:

```python
def _main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Ingest curated official national admission regulations"
    )
    parser.add_argument("--sources", default=None,
                        help="path to national_sources.json (default: committed seed)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    sources = load_national_sources(args.sources)
    if not sources:
        print("No national sources configured. Add rows to "
              "ingestion/knowledge/seeds/national_sources.json first.")
        return 0

    results = ingest_sources(sources, KnowledgePipeline())

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

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_ingest_national.py -q`
Expected: PASS (5 passed — Task 1's 3 + these 2)

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/ingest_national.py tests/ingestion/knowledge/test_ingest_national.py
git commit -m "feat: wire ingest_national CLI entrypoint"
```

---

## Manual verification (requires Docker DB + network)

These are not part of the offline suite (they hit `datafiles.chinhphu.vn` and need the pgvector DB + inference gateway for embeddings). Run once to confirm the end-to-end path:

```bash
docker compose up -d --wait db
.venv/bin/python -m ingestion.knowledge.ingest_national
# Expect: OK   https://datafiles.chinhphu.vn/cpp/files/vbpq/2022/08/08-bgddt.signed.pdf
#         Done: 1 processed (ok=1 skip=0 fail=0)

# Re-run is idempotent (content_hash skip):
.venv/bin/python -m ingestion.knowledge.ingest_national
# Expect: SKIP  ...   Done: 1 processed (ok=0 skip=1 fail=0)
```

Confirm the row landed under the national scope:

```bash
docker compose exec db psql -U postgres -d admission -c \
  "SELECT school, document_type, source_url FROM knowledge_chunks WHERE school='MOET' LIMIT 3;"
# Expect at least one row: MOET | national_regulation | https://datafiles.chinhphu.vn/.../08-bgddt.signed.pdf
```

## Done when
- `python -m ingestion.knowledge.ingest_national` ingests every curated row under `school="MOET"`, `document_type="national_regulation"`, isolates per-URL failures, and prints an OK/SKIP/FAIL summary.
- Re-running skips unchanged URLs (`content_hash`).
- Offline suite green: `.venv/bin/python -m pytest tests/ingestion/knowledge -q`
