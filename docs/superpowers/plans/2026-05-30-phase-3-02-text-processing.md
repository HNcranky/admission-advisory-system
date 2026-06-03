# Phase 3 · Plan 02 — Text Processing (PDF Pages + Chunker) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn fetched bytes into clean, page-marked text and split that text into deterministic, structure-aware character-window chunks with character-offset spans.

**Architecture:** Two pure-logic modules under `ingestion/knowledge/`. `pdf_pages.py` extracts per-page text via pdfplumber and joins it with `[Trang N]` markers. `chunker.py` packs natural blocks (blank-line / marker boundaries) into ~1800-char windows with 256-char overlap; spans are character offsets into the input text so the idempotency key `(source_url, span_start, span_end)` is stable across re-runs. No DB, no network.

**Tech Stack:** Python, pdfplumber (already in `requirements.txt`), pytest.

**Spec:** [`2026-05-30-phase-3-data-collection-design.md`](../specs/2026-05-30-phase-3-data-collection-design.md) §3–§4.

---

### Task 1: Chunk-size settings constants

**Files:**
- Modify: `ingestion/config/settings.py` (append after the embeddings block, ~line 63)
- Test: `tests/ingestion/test_chunk_settings.py`

- [ ] **Step 1: Write the failing test**

`tests/ingestion/test_chunk_settings.py`:
```python
from ingestion.config import settings


def test_chunk_size_default():
    assert settings.CHUNK_SIZE == 1800


def test_chunk_overlap_default():
    assert settings.CHUNK_OVERLAP == 256
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ingestion/test_chunk_settings.py -v`
Expected: FAIL — `AttributeError: module 'ingestion.config.settings' has no attribute 'CHUNK_SIZE'`.

- [ ] **Step 3: Add the constants**

In `ingestion/config/settings.py`, add immediately after the `EMBEDDING_DIM = ...` line:
```python
# --- Knowledge chunking (Phase 3) ----------------------------------------
# Structure-aware char window. ~1800 chars ≈ 512 tokens for Vietnamese.
# Spans are character offsets → deterministic → stable idempotency key.
CHUNK_SIZE = int(os.getenv("KNOWLEDGE_CHUNK_SIZE", 1800))
CHUNK_OVERLAP = int(os.getenv("KNOWLEDGE_CHUNK_OVERLAP", 256))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ingestion/test_chunk_settings.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add ingestion/config/settings.py tests/ingestion/test_chunk_settings.py
git commit -m "feat(knowledge): add CHUNK_SIZE/CHUNK_OVERLAP settings"
```

---

### Task 2: `chunker.py` — structure-aware char-window splitter

**Files:**
- Create: `ingestion/knowledge/chunker.py`
- Test: `tests/ingestion/knowledge/test_chunker.py`

- [ ] **Step 1: Write the failing test**

`tests/ingestion/knowledge/test_chunker.py`:
```python
from ingestion.knowledge.chunker import Chunk, split_into_chunks


def test_empty_text_returns_no_chunks():
    assert split_into_chunks("") == []


def test_short_text_is_single_chunk():
    text = "Học phí năm 2026 là 30 triệu đồng."
    chunks = split_into_chunks(text, size=1800, overlap=256)
    assert len(chunks) == 1
    assert chunks[0].span_start == 0
    assert chunks[0].span_end == len(text)
    assert chunks[0].chunk_text == text


def test_chunk_text_matches_its_span():
    text = ("Đoạn một về học phí.\n\n"
            "Đoạn hai về học bổng.\n\n"
            "Đoạn ba về ký túc xá.")
    for c in split_into_chunks(text, size=25, overlap=5):
        assert c.chunk_text == text[c.span_start:c.span_end].strip()


def test_no_chunk_exceeds_size():
    text = "x" * 50 + "\n\n" + "y" * 50 + "\n\n" + "z" * 50
    for c in split_into_chunks(text, size=40, overlap=8):
        assert (c.span_end - c.span_start) <= 40


def test_spans_are_deterministic_across_runs():
    text = "A" * 30 + "\n\n" + "B" * 30 + "\n\n" + "C" * 30
    run1 = [(c.span_start, c.span_end) for c in split_into_chunks(text, size=35, overlap=7)]
    run2 = [(c.span_start, c.span_end) for c in split_into_chunks(text, size=35, overlap=7)]
    assert run1 == run2
    assert len(run1) >= 2  # forced into multiple chunks


def test_consecutive_chunks_overlap():
    text = "A" * 30 + "\n\n" + "B" * 30 + "\n\n" + "C" * 30
    chunks = split_into_chunks(text, size=35, overlap=7)
    # next chunk starts before previous chunk ends → overlap window
    assert chunks[1].span_start < chunks[0].span_end


def test_oversized_block_is_hard_split():
    text = "Z" * 100  # one block, no boundaries, larger than size
    chunks = split_into_chunks(text, size=40, overlap=0)
    assert len(chunks) >= 3
    assert all((c.span_end - c.span_start) <= 40 for c in chunks)


def test_page_marker_is_preserved_in_chunk_text():
    text = "[Trang 1]\nHọc phí.\n\n[Trang 2]\nHọc bổng."
    chunks = split_into_chunks(text, size=1800, overlap=256)
    joined = " ".join(c.chunk_text for c in chunks)
    assert "[Trang 1]" in joined
    assert "[Trang 2]" in joined
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ingestion/knowledge/test_chunker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingestion.knowledge.chunker'`.

- [ ] **Step 3: Write minimal implementation**

`ingestion/knowledge/chunker.py`:
```python
import re
from dataclasses import dataclass

from ingestion.config.settings import CHUNK_SIZE, CHUNK_OVERLAP

# Blank-line block boundary (also matches the line before a "[Trang N]" marker
# because markers are emitted preceded by a blank line in pdf_pages.py).
_BLOCK_SEP = re.compile(r"\n[ \t]*\n")
# Sentence-ish cut points for hard-splitting an oversized single block.
_SENTENCE_END = re.compile(r"[.!?。]\s|\n")


@dataclass
class Chunk:
    chunk_text: str
    span_start: int
    span_end: int


def _block_break_offsets(text: str) -> list[int]:
    """Sorted candidate cut offsets at block boundaries, plus end-of-text."""
    offs = {len(text)}
    for m in _BLOCK_SEP.finditer(text):
        if m.start() > 0:
            offs.add(m.start())
    return sorted(offs)


def _largest_le(values: list[int], limit: int) -> int | None:
    best = None
    for v in values:
        if v <= limit:
            best = v
        else:
            break
    return best


def _sentence_cut(text: str, start: int, hard_limit: int) -> int:
    """Last sentence boundary in (start, hard_limit], else hard_limit."""
    window = text[start:hard_limit]
    last = None
    for m in _SENTENCE_END.finditer(window):
        last = m.end()
    if last is not None and last > 0:
        return start + last
    return hard_limit


def split_into_chunks(
    text: str,
    size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[Chunk]:
    n = len(text)
    if n == 0:
        return []

    breaks = _block_break_offsets(text)
    chunks: list[Chunk] = []
    start = 0
    while start < n:
        hard_limit = start + size
        if hard_limit >= n:
            end = n
        else:
            candidate = _largest_le(breaks, hard_limit)
            if candidate is not None and candidate > start:
                end = candidate
            else:
                end = _sentence_cut(text, start, hard_limit)

        body = text[start:end].strip()
        if body:
            chunks.append(Chunk(chunk_text=body, span_start=start, span_end=end))

        if end >= n:
            break
        start = max(end - overlap, start + 1)

    return chunks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ingestion/knowledge/test_chunker.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/chunker.py tests/ingestion/knowledge/test_chunker.py
git commit -m "feat(knowledge): add structure-aware char-window chunker"
```

---

### Task 3: `pdf_pages.py` — page-aware PDF extraction with markers

**Files:**
- Create: `ingestion/knowledge/pdf_pages.py`
- Test: `tests/ingestion/knowledge/test_pdf_pages.py`

- [ ] **Step 1: Write the failing test**

`tests/ingestion/knowledge/test_pdf_pages.py`:
```python
from ingestion.knowledge import pdf_pages


def test_pages_to_marked_text_inserts_trang_markers():
    pages = [(1, "Học phí năm 2026."), (2, "Học bổng KKHT.")]
    text = pdf_pages.pages_to_marked_text(pages)
    assert text.startswith("[Trang 1]\n")
    assert "[Trang 2]\n" in text
    assert "Học phí năm 2026." in text
    assert "Học bổng KKHT." in text


def test_pages_to_marked_text_separates_pages_with_blank_line():
    pages = [(1, "A"), (2, "B")]
    text = pdf_pages.pages_to_marked_text(pages)
    # blank line between pages so the chunker treats each page as a block
    assert "\n\n[Trang 2]" in text


def test_pages_to_marked_text_skips_empty_pages():
    pages = [(1, "A"), (2, "   "), (3, "C")]
    text = pdf_pages.pages_to_marked_text(pages)
    assert "[Trang 2]" not in text
    assert "[Trang 3]" in text


def test_extract_pages_reads_real_pdf():
    # Minimal valid one-page PDF generated inline so the test needs no fixture file.
    pdf_bytes = _one_page_pdf("Hello Trang")
    pages = pdf_pages.extract_pages(pdf_bytes)
    assert len(pages) == 1
    assert pages[0][0] == 1
    assert "Hello" in pages[0][1]


def _one_page_pdf(text: str) -> bytes:
    # Build a tiny PDF with pdfplumber's dependency (pdfminer) round-trippable
    # text using reportlab if available; otherwise skip cleanly.
    import pytest
    reportlab = pytest.importorskip("reportlab")
    from reportlab.pdfgen import canvas
    from io import BytesIO

    buf = BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 700, text)
    c.showPage()
    c.save()
    return buf.getvalue()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ingestion/knowledge/test_pdf_pages.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingestion.knowledge.pdf_pages'`.

- [ ] **Step 3: Write minimal implementation**

`ingestion/knowledge/pdf_pages.py`:
```python
import io
import logging

import pdfplumber

logger = logging.getLogger(__name__)


def extract_pages(content: bytes) -> list[tuple[int, str]]:
    """Extract per-page text from a PDF as [(page_no, text), ...] (1-indexed)."""
    pages: list[tuple[int, str]] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            pages.append((i, text))
    logger.info("Extracted %d PDF pages", len(pages))
    return pages


def pages_to_marked_text(pages: list[tuple[int, str]]) -> str:
    """Join pages into one string, each non-empty page prefixed by `[Trang N]`
    and separated by a blank line so the chunker treats pages as blocks."""
    blocks: list[str] = []
    for page_no, text in pages:
        body = (text or "").strip()
        if not body:
            continue
        blocks.append(f"[Trang {page_no}]\n{body}")
    return "\n\n".join(blocks)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ingestion/knowledge/test_pdf_pages.py -v`
Expected: PASS (the real-PDF test self-skips if `reportlab` is absent; the three `pages_to_marked_text` tests always run and pass).

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/pdf_pages.py tests/ingestion/knowledge/test_pdf_pages.py
git commit -m "feat(knowledge): add page-aware PDF extraction with [Trang N] markers"
```

---

### Task 4: Plan-level verification

- [ ] **Step 1: Run the full plan test suite**

Run: `pytest tests/ingestion/test_chunk_settings.py tests/ingestion/knowledge/test_chunker.py tests/ingestion/knowledge/test_pdf_pages.py -v`
Expected: PASS (all green; the one PDF test may show `SKIPPED` without reportlab).

- [ ] **Step 2: Confirm admission parsers untouched**

Run: `git diff --name-only -- ingestion/parsers`
Expected: empty output.

## Deliverable

`split_into_chunks(text)` → deterministic `Chunk(chunk_text, span_start, span_end)` list; `extract_pages(bytes)` + `pages_to_marked_text(pages)` → page-marked text for PDFs. **Consumed by Plan 05 (pipeline).**
