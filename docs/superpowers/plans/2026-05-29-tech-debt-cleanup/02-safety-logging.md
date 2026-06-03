# Slice 02 — Safety & observability logging

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Surface three currently-silent behaviours: mock retrieval bypassing the DB, trace extractor failures, and disabled SSL verification during crawls.

**Architecture:** Three small, independent logging/config changes. Default runtime behaviour is preserved; only visibility (and an opt-in SSL flag) is added.

**Tech Stack:** Python 3.12, `logging`, `requests`, pytest (`caplog`, `monkeypatch`).

**Spec:** `docs/superpowers/specs/2026-05-29-tech-debt-cleanup-design.md` (items B1, B2, B3)

**Depends on:** nothing. **Branch:** `chore/stabilize-cleanup`.

> Test commands use `.venv/Scripts/python.exe -m pytest`. These tests use fakes/`monkeypatch` and need no live DB or network.

---

## Task 1: Warn when mock retrieval bypasses the DB

**Files:**
- Modify: `services/retrieval_service.py` (top of file + `fetch_candidates`, around lines 51-54)
- Test: `tests/services/test_retrieval_service.py` (add a test)

- [ ] **Step 1: Write the failing test**

Append to `tests/services/test_retrieval_service.py`:

```python
import logging

import services.retrieval_service as retrieval_service


def test_fetch_candidates_warns_on_mock_bypass(monkeypatch, caplog):
    monkeypatch.setattr(retrieval_service, "mock_conflicts_enabled", lambda: True)
    monkeypatch.setattr(
        retrieval_service, "build_mock_conflict_candidates", lambda filters, limit: []
    )

    with caplog.at_level(logging.WARNING, logger="services.retrieval_service"):
        result = retrieval_service.fetch_candidates({"admission_year": 2026})

    assert result == []
    assert any(
        "ADVISORY_MOCK_CONFLICTS" in record.message and "bypass" in record.message.lower()
        for record in caplog.records
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/services/test_retrieval_service.py::test_fetch_candidates_warns_on_mock_bypass -v`
Expected: FAIL — no warning is emitted.

- [ ] **Step 3: Add the logger and warning**

At the top of `services/retrieval_service.py`, after the existing imports, add (if not already present):

```python
import logging

logger = logging.getLogger(__name__)
```

In `fetch_candidates`, replace the mock branch (currently lines 52-54):

```python
    # ADVISORY_MOCK_CONFLICTS keeps local/demo conflict retrieval off the DB path.
    if mock_conflicts_enabled():
        return build_mock_conflict_candidates(filters=filters, limit=limit)
```

with:

```python
    # ADVISORY_MOCK_CONFLICTS keeps local/demo conflict retrieval off the DB path.
    if mock_conflicts_enabled():
        logger.warning(
            "ADVISORY_MOCK_CONFLICTS is enabled: bypassing the database and "
            "returning in-memory mock conflict candidates. Do NOT use in production."
        )
        return build_mock_conflict_candidates(filters=filters, limit=limit)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/services/test_retrieval_service.py::test_fetch_candidates_warns_on_mock_bypass -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/retrieval_service.py tests/services/test_retrieval_service.py
git commit -m "feat: warn when mock retrieval bypasses the database"
```

---

## Task 2: Log the trace extractor-error path

**Files:**
- Modify: `services/tracing/agent_tracer.py:36-39`
- Test: `tests/services/tracing/test_agent_tracer.py` (add a test)

- [ ] **Step 1: Write the failing test**

Append to `tests/services/tracing/test_agent_tracer.py`:

```python
import logging

from services.tracing.agent_tracer import traced


class _NoopRepo:
    def start_event(self, run_id, stage, sequence):
        return 1

    def complete_event(self, event_id, output_json):
        return None

    def fail_event(self, event_id, error_text):
        return None


class _State:
    trace_run_id = "run-1"


def test_traced_logs_when_extractor_raises(caplog):
    def agent_fn(state):
        return {"ok": True}

    def bad_extractor(result, state):
        raise ValueError("boom")

    wrapped = traced("reason", 3, bad_extractor, repository=_NoopRepo())(agent_fn)

    with caplog.at_level(logging.WARNING, logger="services.tracing.agent_tracer"):
        result = wrapped(_State())

    assert result == {"ok": True}
    assert any(
        "extractor" in record.message and "reason" in record.message
        for record in caplog.records
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/services/tracing/test_agent_tracer.py::test_traced_logs_when_extractor_raises -v`
Expected: FAIL — the extractor error is swallowed into `output_json` without a log record.

- [ ] **Step 3: Add the warning**

In `services/tracing/agent_tracer.py`, replace lines 36-39:

```python
            try:
                output_json = output_extractor(result, state)
            except Exception as exc:
                output_json = {"_extractor_error": repr(exc)}
```

with:

```python
            try:
                output_json = output_extractor(result, state)
            except Exception as exc:
                logger.warning("trace extractor failed for stage=%s: %r", stage, exc)
                output_json = {"_extractor_error": repr(exc)}
```

(`logger` already exists at line 8.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/services/tracing/test_agent_tracer.py::test_traced_logs_when_extractor_raises -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/tracing/agent_tracer.py tests/services/tracing/test_agent_tracer.py
git commit -m "feat: log trace extractor failures instead of swallowing them"
```

---

## Task 3: Make SSL verification explicit and configurable for crawling

**Files:**
- Modify: `ingestion/config/settings.py` (after line 59, with the other `FETCH_` settings)
- Modify: `ingestion/fetchers/http_fetcher.py:15`, `:24-29`, and the `requests.get` call site
- Modify: `.env.example` (document the new flag)
- Test: `tests/ingestion/test_http_fetcher_ssl.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/ingestion/test_http_fetcher_ssl.py`:

```python
import logging

import ingestion.fetchers.http_fetcher as http_fetcher


class _FakeResponse:
    content = b"<html>ok</html>"
    url = "https://example.test/page"
    headers = {"Content-Type": "text/html"}
    status_code = 200

    def raise_for_status(self):
        return None


def _patch_requests(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, timeout=None, verify=None, allow_redirects=None):
        captured["verify"] = verify
        return _FakeResponse()

    monkeypatch.setattr(http_fetcher.requests, "get", fake_get)
    return captured


def test_http_fetch_warns_when_ssl_verification_disabled(monkeypatch, caplog):
    captured = _patch_requests(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="ingestion.fetchers.http_fetcher"):
        http_fetcher.http_fetch("https://example.test/page", verify_ssl=False)

    assert captured["verify"] is False
    assert any("SSL verification" in record.message for record in caplog.records)


def test_http_fetch_no_warning_when_ssl_verification_enabled(monkeypatch, caplog):
    captured = _patch_requests(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="ingestion.fetchers.http_fetcher"):
        http_fetcher.http_fetch("https://example.test/page", verify_ssl=True)

    assert captured["verify"] is True
    assert not any("SSL verification" in record.message for record in caplog.records)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/ingestion/test_http_fetcher_ssl.py -v`
Expected: FAIL — no "SSL verification" warning is emitted.

- [ ] **Step 3: Add the setting**

In `ingestion/config/settings.py`, after line 59 (`FETCH_RETRY_BACKOFF = ...`), add:

```python
# Default OFF: several official .gov.vn admission sources ship broken certs.
# Set ADVISORY_FETCH_VERIFY_SSL=true to enforce verification.
FETCH_VERIFY_SSL = os.getenv("ADVISORY_FETCH_VERIFY_SSL", "false").strip().lower() in (
    "1",
    "true",
    "yes",
)
```

- [ ] **Step 4: Update `http_fetcher.py`**

Remove the blanket suppression at line 15 (`urllib3.disable_warnings(...)`) — delete that line. Update the import block (lines 10-12) to also import the new setting:

```python
from ingestion.config.settings import (
    FETCH_TIMEOUT, FETCH_MAX_RETRIES, FETCH_RETRY_BACKOFF, USER_AGENTS,
    FETCH_VERIFY_SSL,
)
```

Change the signature default (line 28) from `verify_ssl: bool = False,` to:

```python
    verify_ssl: bool = FETCH_VERIFY_SSL,
```

Immediately after the `headers = {...}` block (before `last_exception = None`, around line 51), add:

```python
    if not verify_ssl:
        logger.warning(
            "SSL verification is disabled for %s. "
            "Set ADVISORY_FETCH_VERIFY_SSL=true to enforce it.",
            url,
        )
```

(`logger` already exists at line 17. If the `import urllib3` line at the top is now unused, remove it.)

- [ ] **Step 5: Document the flag in `.env.example`**

Add a line under the existing fetch/LLM config in `.env.example`:

```
# Crawl: verify TLS certs of crawled sources. Default false (some official sources have broken certs).
ADVISORY_FETCH_VERIFY_SSL=false
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/ingestion/test_http_fetcher_ssl.py -v`
Expected: PASS (both tests).

- [ ] **Step 7: Commit**

```bash
git add ingestion/config/settings.py ingestion/fetchers/http_fetcher.py .env.example tests/ingestion/test_http_fetcher_ssl.py
git commit -m "feat: make crawl SSL verification configurable and logged"
```
