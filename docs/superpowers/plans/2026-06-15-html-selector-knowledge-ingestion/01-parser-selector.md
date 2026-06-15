# Plan 01 — Parser: per-source CSS selector

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach `parse_html` to extract a caller-specified CSS region, failing loud when the selector matches nothing.

**Architecture:** Add a `ContentSelectorNotFound` exception and a `selector` keyword to `parse_html`. When `selector` is given, use `soup.select_one`; on no match, raise. When `selector` is `None`, the existing `_find_content_area` fallback chain runs unchanged.

**Tech Stack:** Python, BeautifulSoup (`bs4`), pytest.

---

### Task 1: `selector` support in `parse_html`

**Files:**
- Modify: `ingestion/parsers/html_parser.py`
- Test: `tests/ingestion/test_html_parser_selector.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/ingestion/test_html_parser_selector.py`:

```python
import pytest

from ingestion.parsers.html_parser import ContentSelectorNotFound, parse_html

HTML = b"""
<html><body>
  <nav>MENU LINK</nav>
  <div id="content"><p>Noi dung chinh cua trang du dai de tao mot chunk hop le.</p></div>
  <footer>FOOTER JUNK</footer>
</body></html>
"""


def test_selector_extracts_only_targeted_region():
    parsed = parse_html(HTML, "https://x", selector="#content")
    assert "Noi dung chinh" in parsed.text
    assert "MENU LINK" not in parsed.text
    assert "FOOTER JUNK" not in parsed.text


def test_selector_no_match_raises():
    with pytest.raises(ContentSelectorNotFound):
        parse_html(HTML, "https://x", selector="#nope")


def test_selector_none_uses_fallback_unchanged():
    # Default path: _find_content_area finds <div id="content"> via its fallback
    # chain, so the region is extracted and nav/footer are still dropped.
    parsed = parse_html(HTML, "https://x")
    assert "Noi dung chinh" in parsed.text
    assert "FOOTER JUNK" not in parsed.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/ingestion/test_html_parser_selector.py -v`
Expected: FAIL — `ImportError: cannot import name 'ContentSelectorNotFound'`.

- [ ] **Step 3: Add the exception class**

In `ingestion/parsers/html_parser.py`, after the existing imports / `logger` line and before `def parse_html(...)`, add:

```python
class ContentSelectorNotFound(Exception):
    """Raised when a caller-supplied CSS selector matches no element."""

    def __init__(self, selector: str, url: str = ""):
        self.selector = selector
        self.url = url
        super().__init__(
            f"CSS selector {selector!r} matched no element on {url or '<html>'}"
        )
```

- [ ] **Step 4: Add the `selector` keyword and the branch**

Change the signature:

```python
def parse_html(content: bytes, url: str = "", selector: str | None = None) -> ParsedContent:
```

Then replace the single line that currently reads:

```python
    content_tag = _find_content_area(soup)
```

with:

```python
    if selector is not None:
        content_tag = soup.select_one(selector)
        if content_tag is None:
            raise ContentSelectorNotFound(selector, url)
    else:
        content_tag = _find_content_area(soup)
```

(The global `script/style/noscript/iframe` decompose above this line is unchanged, so the selected region is already clean.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ingestion/test_html_parser_selector.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Guard against regressions in the existing parser tests**

Run: `.venv/bin/python -m pytest tests/ingestion/test_hust_announcement_html_parser.py -q`
Expected: PASS (unchanged — `selector` defaults to `None`).

- [ ] **Step 7: Commit**

```bash
git add ingestion/parsers/html_parser.py tests/ingestion/test_html_parser_selector.py
git commit -m "feat(parser): optional CSS selector for parse_html"
```
