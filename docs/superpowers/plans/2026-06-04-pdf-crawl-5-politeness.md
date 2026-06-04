# PDF Crawler Politeness (robots.txt + delay) Implementation Plan (5/4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the focused crawler polite — respect `robots.txt` by default (overridable) and allow an optional per-request delay — without disturbing plan 1's existing tests.

**Architecture:** A standalone `robots.py` exposes `build_robots_checker(...) -> allowed(url)->bool` (fetches + caches `robots.txt` per host via stdlib `urllib.robotparser`). `crawl_target` gains two **optional** params — `allowed=None` (no gating by default → plan 1 tests untouched) and `delay=0.0` (no sleep by default). The `crawl` CLI wires `--ignore-robots` and `--delay`.

**Tech Stack:** Python 3.12, stdlib `urllib.robotparser` + `time`, existing `http_fetch`.

This is plan **5 of 4** — an add-on covering spec §6 politeness. Depends on plans 1–2. Independent of plans 3–4.

---

### Task 1: robots.txt checker

**Files:**
- Create: `ingestion/knowledge/crawler/robots.py`
- Test: `tests/ingestion/knowledge/test_crawl_robots.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ingestion/knowledge/test_crawl_robots.py
from ingestion.knowledge.crawler.robots import build_robots_checker


class _FR:
    def __init__(self, body: bytes):
        self.raw_content = body


def test_respect_false_allows_everything():
    allowed = build_robots_checker(respect=False)
    assert allowed("https://a.vn/anything")


def test_disallow_blocks_matching_path():
    def fetch(url):
        return _FR(b"User-agent: *\nDisallow: /private\n")

    allowed = build_robots_checker(fetch=fetch, respect=True)
    assert allowed("https://a.vn/public/x")
    assert not allowed("https://a.vn/private/x")


def test_missing_robots_allows():
    def fetch(url):
        raise RuntimeError("404")

    allowed = build_robots_checker(fetch=fetch, respect=True)
    assert allowed("https://a.vn/anything")


def test_robots_fetched_once_per_host():
    calls = []

    def fetch(url):
        calls.append(url)
        return _FR(b"User-agent: *\nDisallow:\n")

    allowed = build_robots_checker(fetch=fetch, respect=True)
    allowed("https://a.vn/1")
    allowed("https://a.vn/2")
    assert calls == ["https://a.vn/robots.txt"]   # parsed once, then cached
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_robots.py -q`
Expected: FAIL — `ModuleNotFoundError: ... robots`

- [ ] **Step 3: Implement build_robots_checker**

```python
# ingestion/knowledge/crawler/robots.py
"""robots.txt gate for the focused crawler (spec §6 politeness)."""
import logging
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from ingestion.fetchers.http_fetcher import http_fetch

logger = logging.getLogger(__name__)


def _load_robots(url: str, fetch):
    parts = urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        body = fetch(robots_url).raw_content.decode("utf-8", errors="replace")
    except Exception as exc:  # missing/blocked robots.txt => no restrictions
        logger.info("no robots.txt at %s: %r", robots_url, exc)
        return None
    rp = RobotFileParser()
    rp.parse(body.splitlines())
    return rp


def build_robots_checker(*, fetch=http_fetch, user_agent: str = "*",
                         respect: bool = True):
    """Return allowed(url)->bool. respect=False => always allow.
    robots.txt is fetched + parsed once per host and cached."""
    if not respect:
        return lambda url: True

    cache: dict[str, RobotFileParser | None] = {}

    def allowed(url: str) -> bool:
        host = urlsplit(url).netloc.lower()
        if host not in cache:
            cache[host] = _load_robots(url, fetch)
        rp = cache[host]
        return True if rp is None else rp.can_fetch(user_agent, url)

    return allowed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_robots.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/crawler/robots.py tests/ingestion/knowledge/test_crawl_robots.py
git commit -m "feat: add robots.txt checker for crawler politeness"
```

---

### Task 2: Wire `allowed` gate + `delay` into `crawl_target`

**Files:**
- Modify: `ingestion/knowledge/crawler/pdf_crawler.py`
- Test: `tests/ingestion/knowledge/test_crawl_target.py` (append)

- [ ] **Step 1: Write the failing test (append)**

```python
# append to tests/ingestion/knowledge/test_crawl_target.py
def test_crawl_skips_pages_blocked_by_allowed_gate():
    site = {
        "https://a.vn/seed": _page(
            '<a href="/seed/open.pdf">open</a>'
            '<a href="/seed/blocked">blocked page</a>'
        ),
        "https://a.vn/seed/blocked": _page('<a href="/seed/secret.pdf">secret</a>'),
    }

    def fetch(url):
        return site[url]

    target = CrawlTarget(school="HUST", seeds=["https://a.vn/seed"],
                         allow_domains=["a.vn"], max_depth=3, max_pages=50)
    allowed = lambda url: "/seed/blocked" not in url   # block the sub page

    pdfs = crawl_target(target, fetch=fetch, head=_no_head, sitemap=False,
                        allowed=allowed)
    urls = {p.url for p in pdfs}
    # the blocked page is never fetched, so its secret.pdf is never discovered
    assert urls == {"https://a.vn/seed/open.pdf"}
```

(`_page`, `_no_head`, `CrawlTarget`, `crawl_target` are already imported/defined in this test file from plan 1.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_target.py::test_crawl_skips_pages_blocked_by_allowed_gate -q`
Expected: FAIL — `TypeError: crawl_target() got an unexpected keyword argument 'allowed'`

- [ ] **Step 3: Add `import time` and the two optional params**

In `ingestion/knowledge/crawler/pdf_crawler.py`, add `import time` to the import block (just below `import logging`).

Change the `crawl_target` signature from:

```python
def crawl_target(target: CrawlTarget, *, fetch=http_fetch, head=fetch_head,
                 sitemap: bool = True) -> list[CandidatePdf]:
```

to:

```python
def crawl_target(target: CrawlTarget, *, fetch=http_fetch, head=fetch_head,
                 sitemap: bool = True, allowed=None,
                 delay: float = 0.0) -> list[CandidatePdf]:
```

Then, inside the `while` loop, right after `visited.add(url)` and BEFORE the `try: fr = fetch(url)` block, insert the robots gate:

```python
        if allowed is not None and not allowed(url):
            logger.info("robots.txt disallows %s", url)
            continue
```

And right after `pages_crawled += 1`, insert the throttle:

```python
        if delay:
            time.sleep(delay)
```

(Both default to off — `allowed=None` and `delay=0.0` — so every existing plan-1 test keeps passing unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_target.py -q`
Expected: PASS (4 passed — the 3 original + the new gate test)

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/crawler/pdf_crawler.py tests/ingestion/knowledge/test_crawl_target.py
git commit -m "feat: support robots gate and request delay in crawl_target"
```

---

### Task 3: Wire `--ignore-robots` / `--delay` into the `crawl` CLI

**Files:**
- Modify: `ingestion/knowledge/crawl.py` (the `_main` function from plan 2)
- Test: `tests/ingestion/knowledge/test_crawl_cli.py` (append)

- [ ] **Step 1: Write the failing test (append) — assert the CLI builds a robots-gated crawl**

```python
# append to tests/ingestion/knowledge/test_crawl_cli.py
import ingestion.knowledge.crawl as crawl_mod


def test_main_passes_robots_gate_to_crawl_target(tmp_path, monkeypatch):
    captured = {}

    def fake_crawl_target(target, *, sitemap=True, allowed=None, delay=0.0):
        captured["allowed"] = allowed
        captured["delay"] = delay
        return []

    monkeypatch.setattr(crawl_mod, "crawl_target", fake_crawl_target)
    monkeypatch.setattr(crawl_mod, "load_targets",
                        lambda: [CrawlTarget(school="HUST", seeds=["https://a.vn/s"],
                                             allow_domains=["a.vn"])])

    class _DocRepo:
        def get_document_by_url(self, url):
            return None

    monkeypatch.setattr(
        "services.knowledge.repository.KnowledgeDocumentRepository",
        lambda: _DocRepo(),
    )

    rc = crawl_mod._main(["--school", "HUST", "--delay", "0.5",
                          "--manifest", str(tmp_path / "m.json")])

    assert rc == 0
    assert callable(captured["allowed"])         # robots gate wired by default
    assert captured["allowed"]("https://a.vn/x") in (True, False)
    assert captured["delay"] == 0.5
```

(`CrawlTarget` is already imported in this test file from plan 2.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_cli.py::test_main_passes_robots_gate_to_crawl_target -q`
Expected: FAIL — `unrecognized arguments: --delay` (argparse error / SystemExit)

- [ ] **Step 3: Update `_main` in `ingestion/knowledge/crawl.py`**

Add the import near the top of `crawl.py`:

```python
from ingestion.fetchers.http_fetcher import http_fetch
from ingestion.knowledge.crawler.robots import build_robots_checker
```

Add the two CLI args (next to `--no-sitemap`):

```python
    parser.add_argument("--ignore-robots", action="store_true",
                        help="do not consult robots.txt")
    parser.add_argument("--delay", type=float, default=0.0,
                        help="seconds to sleep between page fetches")
```

Replace the `build_manifest(...)` call so it builds a robots-gated, throttled crawl closure:

```python
    checker = build_robots_checker(fetch=http_fetch, respect=not args.ignore_robots)

    def crawl(target, sitemap=True):
        return crawl_target(target, sitemap=sitemap, allowed=checker,
                            delay=args.delay)

    merged = build_manifest(
        targets, existing, crawl=crawl,
        doc_repo=KnowledgeDocumentRepository(),
        discovered_at=date.today().isoformat(), sitemap=not args.no_sitemap,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_cli.py -q`
Expected: PASS (4 passed — plan 2's 3 + this one)

- [ ] **Step 5: Run the full crawler suite**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge -q`
Expected: PASS (all green)

- [ ] **Step 6: Commit**

```bash
git add ingestion/knowledge/crawl.py tests/ingestion/knowledge/test_crawl_cli.py
git commit -m "feat: wire robots.txt respect and crawl delay into crawl CLI"
```

---

## Done when
- The crawler skips `robots.txt`-disallowed pages by default; `--ignore-robots` overrides; `--delay` throttles page fetches.
- All existing plan-1/2 tests still pass (the new params are opt-in).
- Spec §6 politeness is fully covered.
