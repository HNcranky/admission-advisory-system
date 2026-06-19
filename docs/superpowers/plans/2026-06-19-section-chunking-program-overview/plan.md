# Section Chunking with Contextual Headers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `whole_page` chunking for HUST program-overview pages with a `by_section` strategy that splits each page on `## ` headings and prepends a `{program} — {section}` contextual header to every chunk, so program-named sub-topic queries retrieve the correct section.

**Architecture:** The HTML parser already renders sections as `## <title>` markdown. A new `chunk_by_section` splits on those headings and embeds a program+section header into each chunk. The parser gains a `content_label` (program name from breadcrumb/title/slug). The pipeline parses once, threads the label into chunking, and stores it in the `program` column. Retrieval is unchanged — the header makes plain cosine search land on the right program's right section.

**Tech Stack:** Python, BeautifulSoup (`html.parser`), pgvector, pytest. Pydantic v2.

**Spec:** `docs/superpowers/specs/2026-06-19-section-chunking-program-overview-design.md`

---

## Task 1: Parser emits `content_label`

**Files:**
- Modify: `ingestion/models/pipeline_models.py:75-98` (add field to `ParsedContent`)
- Modify: `ingestion/parsers/html_parser.py` (extract label, set on result)
- Test: `tests/ingestion/test_html_parser_selector.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/ingestion/test_html_parser_selector.py`:

```python
HTML_WITH_BREADCRUMB = b"""
<html><head><title>Title Tag</title></head><body><div class="container">
  <ol class="breadcrumb">
    <li class="breadcrumb-item"><a>Trang chu</a></li>
    <li class="breadcrumb-item active">Ky thuat O to</li>
  </ol>
  <section><h2 class="sec-title">Tong quan</h2><p>Noi dung.</p></section>
</div></body></html>
"""

HTML_NO_BREADCRUMB = b"""
<html><head><title>Title Tag</title></head><body><div class="container">
  <section><h2 class="sec-title">Tong quan</h2><p>Noi dung.</p></section>
</div></body></html>
"""

HTML_NO_LABEL_SOURCES = b"""
<html><body><div class="container">
  <section><h2 class="sec-title">Tong quan</h2><p>Noi dung.</p></section>
</div></body></html>
"""


def test_content_label_from_breadcrumb_active():
    parsed = parse_html(HTML_WITH_BREADCRUMB, "https://x/ky-thuat-o-to")
    assert parsed.content_label == "Ky thuat O to"


def test_content_label_falls_back_to_title():
    parsed = parse_html(HTML_NO_BREADCRUMB, "https://x/ky-thuat-o-to")
    assert parsed.content_label == "Title Tag"


def test_content_label_falls_back_to_slug():
    parsed = parse_html(HTML_NO_LABEL_SOURCES, "https://x/ky-thuat-o-to")
    assert parsed.content_label == "ky thuat o to"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/ingestion/test_html_parser_selector.py -k content_label -q`
Expected: FAIL — `ParsedContent` has no attribute `content_label`.

- [ ] **Step 3: Add the field to `ParsedContent`**

In `ingestion/models/pipeline_models.py`, after `title: Optional[str] = None` (line 78):

```python
    title: Optional[str] = None
    content_label: Optional[str] = Field(
        default=None,
        description="Clean page label (e.g. program name) for chunk headers",
    )
```

- [ ] **Step 4: Implement label extraction in the parser**

In `ingestion/parsers/html_parser.py`, add this helper next to the other private
helpers (e.g. after `_to_markdown`):

```python
def _extract_content_label(
    soup: BeautifulSoup, title: str | None, url: str
) -> str | None:
    """Clean page label: breadcrumb-active → <title> → de-slugified URL tail."""
    active = soup.select_one("li.breadcrumb-item.active")
    if active:
        text = active.get_text(" ", strip=True)
        if text:
            return text
    if title:
        return title
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    if slug:
        return slug.replace("-", " ").strip() or None
    return None
```

In `parse_html`, after the `title` block and before the selector block, compute
the label; then pass it into `ParsedContent(...)`:

```python
    content_label = _extract_content_label(soup, title, url)
```

and in the `ParsedContent(...)` constructor add:

```python
        title=title,
        content_label=content_label,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ingestion/test_html_parser_selector.py -q`
Expected: PASS (all, including the 3 new + existing structure/table tests).

- [ ] **Step 6: Commit**

```bash
git add ingestion/models/pipeline_models.py ingestion/parsers/html_parser.py tests/ingestion/test_html_parser_selector.py
git commit -m "feat(parser): extract content_label (breadcrumb/title/slug) on ParsedContent"
```

---

## Task 2: `chunk_by_section` strategy

**Files:**
- Modify: `ingestion/knowledge/chunker.py` (add `chunk_by_section`, `_label_chunks`; extend `chunk_text`)
- Test: `tests/ingestion/test_chunk_strategy.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/ingestion/test_chunk_strategy.py`:

```python
SECTIONED = (
    "- Trang chu\n- Nganh dao tao\n\n"          # preamble (breadcrumb noise)
    "## Tong quan\n\nNgon ngu: Tieng Anh.\n\n"
    "## Co hoi viec lam\n\nKy su van hanh he thong.\n"
)


def test_by_section_splits_on_headings():
    chunks = chunk_text(SECTIONED, strategy="by_section", context_label="Ky thuat O to")
    bodies = [c.chunk_text for c in chunks]
    assert len(chunks) == 2
    assert any("Co hoi viec lam" in b and "Ky su van hanh" in b for b in bodies)


def test_by_section_prepends_program_section_header():
    chunks = chunk_text(SECTIONED, strategy="by_section", context_label="Ky thuat O to")
    career = next(c.chunk_text for c in chunks if "Ky su van hanh" in c.chunk_text)
    assert career.startswith("Ky thuat O to — Co hoi viec lam\n\n")


def test_by_section_drops_preamble_before_first_heading():
    chunks = chunk_text(SECTIONED, strategy="by_section", context_label="X")
    assert all("Trang chu" not in c.chunk_text for c in chunks)


def test_by_section_no_headings_falls_back_to_one_labeled_chunk():
    chunks = chunk_text("Mot doan khong co heading.", strategy="by_section",
                        context_label="Ky thuat O to")
    assert len(chunks) == 1
    assert chunks[0].chunk_text == "Ky thuat O to\n\nMot doan khong co heading."


def test_by_section_without_label_omits_header():
    chunks = chunk_text("## Tong quan\n\nNoi dung.", strategy="by_section",
                        context_label=None)
    assert chunks[0].chunk_text == "Tong quan\n\nNoi dung."


def test_by_section_oversized_section_subsplits_with_header_on_each():
    body = "Cau van. " * 400  # ~3200 chars, over CHUNK_SIZE 1800
    text = "## Co hoi viec lam\n\n" + body
    chunks = chunk_text(text, strategy="by_section", context_label="X", )
    assert len(chunks) > 1
    assert all(c.chunk_text.startswith("X — Co hoi viec lam\n\n") for c in chunks)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/ingestion/test_chunk_strategy.py -k by_section -q`
Expected: FAIL — `chunk_text()` got an unexpected keyword `context_label` / strategy unknown.

- [ ] **Step 3: Implement the strategy**

In `ingestion/knowledge/chunker.py`, add a section-heading regex near the top
(after the existing `_SENTENCE_END` definition):

```python
# Markdown section heading emitted by the HTML parser's _to_markdown.
_SECTION_HEADING = re.compile(r"(?m)^##\s+(.+?)\s*$")
```

Add these functions (place them above `chunk_text`):

```python
def _label_chunks(label, section_title, body, base_off, size, overlap):
    """One section body → labeled chunk(s); sub-split if larger than size."""
    header = " — ".join(p for p in (label, section_title) if p)
    prefix = f"{header}\n\n" if header else ""
    out: list[Chunk] = []
    if len(body) <= size:
        out.append(Chunk(
            chunk_text=prefix + body,
            span_start=base_off,
            span_end=base_off + len(body),
        ))
    else:
        for sub in split_into_chunks(body, size, overlap):
            out.append(Chunk(
                chunk_text=prefix + sub.chunk_text,
                span_start=base_off + sub.span_start,
                span_end=base_off + sub.span_end,
            ))
    return out


def chunk_by_section(text, context_label=None, *,
                     size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """Split markdown text on '## ' headings; prepend '{label} — {section}'."""
    matches = list(_SECTION_HEADING.finditer(text))
    if not matches:
        body = text.strip()
        if not body:
            return []
        return _label_chunks(context_label, None, body, 0, size, overlap)
    chunks: list[Chunk] = []
    for i, m in enumerate(matches):
        section_title = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if not body:
            continue
        chunks.extend(
            _label_chunks(context_label, section_title, body, m.start(), size, overlap)
        )
    return chunks
```

Extend `chunk_text` — add a `context_label` parameter and a `by_section` branch:

```python
def chunk_text(
    text: str,
    strategy: str = "size",
    *,
    context_label: str | None = None,
    size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
    max_chars: int = WHOLE_PAGE_MAX_CHARS,
) -> list[Chunk]:
```

Inside `chunk_text`, before the `whole_page` branch, add:

```python
    if strategy == "by_section":
        return chunk_by_section(text, context_label, size=size, overlap=overlap)
```

(Leave the existing `whole_page` and default `size` branches unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ingestion/test_chunk_strategy.py -q`
Expected: PASS (all `by_section` + existing strategy tests).

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/chunker.py tests/ingestion/test_chunk_strategy.py
git commit -m "feat(chunker): add by_section strategy with program-section headers"
```

---

## Task 3: Pipeline wiring — parse once, thread label, set program

**Files:**
- Modify: `ingestion/knowledge/pipeline.py` (`_extract_text`, `_chunk_embed_upsert`, `run_for_source`)
- Test: `tests/ingestion/test_pipeline_section_chunking.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/ingestion/test_pipeline_section_chunking.py`:

```python
from ingestion.knowledge.pipeline import KnowledgePipeline


class _Fetch:
    def __init__(self, content):
        self.raw_content = content
        self.content_type = "text/html"
        self.content_hash = "h1"


PAGE = (
    b"<html><head><title>T</title></head><body><div class='container'>"
    b"<ol class='breadcrumb'><li class='breadcrumb-item active'>Ky thuat O to</li></ol>"
    b"<section><h2 class='sec-title'>Co hoi viec lam</h2><p>Ky su van hanh.</p></section>"
    b"</div></body></html>"
)


def test_extract_text_and_label_returns_program_name():
    p = KnowledgePipeline.__new__(KnowledgePipeline)
    text, label = p._extract_text(_Fetch(PAGE), "https://x/ky-thuat-o-to",
                                  selector="div.container")
    assert "Co hoi viec lam" in text
    assert label == "Ky thuat O to"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ingestion/test_pipeline_section_chunking.py -q`
Expected: FAIL — `_extract_text` returns a `str`, not a `(text, label)` tuple.

- [ ] **Step 3: Make `_extract_text` return `(text, label)`**

In `ingestion/knowledge/pipeline.py`, change `_extract_text` (currently lines
89-95):

```python
    def _extract_text(self, fetch_result, url: str, selector: str | None = None):
        """Returns (text, content_label). Label is None for PDFs."""
        ctype = (fetch_result.content_type or "").lower()
        if "pdf" in ctype or url.lower().endswith(".pdf"):
            if selector is not None:
                logger.warning("selector %r ignored for PDF source %s", selector, url)
            return pages_to_marked_text(extract_pages(fetch_result.raw_content)), None
        parsed = parse_html(fetch_result.raw_content, url, selector=selector)
        return parsed.text, parsed.content_label
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ingestion/test_pipeline_section_chunking.py -q`
Expected: PASS.

- [ ] **Step 5: Thread label through `run_for_source` and `_chunk_embed_upsert`**

In `run_for_source` (lines 155-176), update the unpack and the call. Replace:

```python
        try:
            text = self._extract_text(fr, source.source_url, source.selector)
```

with:

```python
        try:
            text, content_label = self._extract_text(fr, source.source_url, source.selector)
```

Then replace the `_chunk_embed_upsert(...)` call with:

```python
        strategy = getattr(source, "chunk_strategy", "size")
        # by_section uses the page label as both the chunk header and program tag
        program = content_label if strategy == "by_section" else source.program
        total, embedded, reused = self._chunk_embed_upsert(
            doc_id, text,
            school=source.school, topic=source.topic, program=program,
            year=source.year, document_type=source.document_type,
            source_url=source.source_url,
            chunk_strategy=strategy,
            context_label=content_label,
        )
```

In `_chunk_embed_upsert` (line 97), add the `context_label` parameter and pass it
to `chunk_text`. Change the signature line:

```python
    def _chunk_embed_upsert(self, doc_id, text, *, school, topic, program,
                            year, document_type, source_url,
                            chunk_strategy="size", context_label=None):
```

and the chunk call (line 103):

```python
        chunks = chunk_text(text, chunk_strategy, context_label=context_label)
```

- [ ] **Step 6: Run the ingestion suite to verify no regression**

Run: `.venv/bin/python -m pytest tests/ingestion/ -q`
Expected: PASS (all).

- [ ] **Step 7: Commit**

```bash
git add ingestion/knowledge/pipeline.py tests/ingestion/test_pipeline_section_chunking.py
git commit -m "feat(ingestion): wire by_section label into chunking and program column"
```

---

## Task 4: Switch seeds to `by_section`

**Files:**
- Modify: `ingestion/knowledge/registry/seeds/knowledge_sources.json`

- [ ] **Step 1: Flip `chunk_strategy` on program-overview entries**

Run:

```bash
.venv/bin/python -c "
import json
from pathlib import Path
from ingestion.knowledge.registry.models import KnowledgeSource
p=Path('ingestion/knowledge/registry/seeds/knowledge_sources.json')
data=json.loads(p.read_text())
n=0
for e in data:
    if e.get('document_type')=='program_overview_page':
        e['chunk_strategy']='by_section'; n+=1
for e in data: KnowledgeSource(**e)   # validate
p.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')
print('by_section on', n, '; all', len(data), 'valid')
"
```

Expected output: `by_section on 68 ; all 79 valid`

- [ ] **Step 2: Commit**

```bash
git add ingestion/knowledge/registry/seeds/knowledge_sources.json
git commit -m "chore(seeds): program-overview pages use by_section chunking"
```

---

## Task 5: Re-ingest HUST and verify retrieval

**Files:** none (operational).

- [ ] **Step 1: Re-ingest HUST**

Run (DB must be up: `docker compose up -d --wait db`):

```bash
set -a && [ -f .env ] && . ./.env; set +a
.venv/bin/python -m ingestion.knowledge.pipeline --school HUST
```

Expected: `Done: 71 source(s) processed`; program pages now report ~3–5 chunks
each (not 1). If a page logs `Unchanged, skipping`, force a re-chunk by clearing
its stored hash, then re-run:

```bash
.venv/bin/python -c "
import os,psycopg2
c=psycopg2.connect(host='localhost',port=5432,dbname=os.getenv('POSTGRES_DB','admission'),user=os.getenv('POSTGRES_USER','postgres'),password=os.getenv('POSTGRES_PASSWORD','postgres'))
cur=c.cursor()
cur.execute(\"update knowledge_documents set content_hash='' where source_url like '%nganh-dao-tao-dai-hoc/%'\")
c.commit(); print('cleared', cur.rowcount)
"
```

- [ ] **Step 2: Verify chunks carry headers and program metadata**

Run:

```bash
set -a && [ -f .env ] && . ./.env; set +a
.venv/bin/python -c "
import os,psycopg2
c=psycopg2.connect(host='localhost',port=5432,dbname=os.getenv('POSTGRES_DB','admission'),user=os.getenv('POSTGRES_USER','postgres'),password=os.getenv('POSTGRES_PASSWORD','postgres'))
cur=c.cursor()
cur.execute(\"select count(*), count(distinct source_url), count(distinct program) from knowledge_chunks where source_url like '%nganh-dao-tao-dai-hoc/%'\")
print('chunks/pages/programs =', cur.fetchone())
cur.execute(\"select left(chunk_text,60) from knowledge_chunks where source_url like '%ky-thuat-o-to' order by span_start\")
for r in cur.fetchall(): print(repr(r[0]))
"
```

Expected: chunks > pages (≈3–5×); `programs` ≈ 68; printed chunk heads look like
`'Kỹ thuật Ô tô — Cơ hội việc làm\\n\\n...'`.

- [ ] **Step 3: Spot-check retrieval ranks the right section**

Run:

```bash
set -a && [ -f .env ] && . ./.env; set +a
.venv/bin/python -c "
from services.knowledge.repository import KnowledgeChunkRepository
from services.inference.embedder import GeminiEmbedder
q='cơ hội việc làm ngành Kỹ thuật Ô tô'
v=GeminiEmbedder().embed([q], task_type='RETRIEVAL_QUERY')[0]
hits=KnowledgeChunkRepository().vector_search(v, school='HUST', topic='program_overview', limit=3)
for h in hits: print(round(h.score,3), '|', h.chunk_text[:70].replace(chr(10),' '))
" 2>/dev/null
```

Expected: top hit is the *Kỹ thuật Ô tô — Cơ hội việc làm* chunk (score clearly
above the others).

- [ ] **Step 4: No commit** (operational step; data only).

---

## Notes for the implementer

- Run all pytest via `.venv/bin/python -m pytest` (repo convention; tests use the
  auto-created `admission_test` DB and never touch dev data).
- Do **not** `git push`. Commit messages must not include any AI attribution
  trailer (`CLAUDE.md` rule).
- `KNOWLEDGE_QA_TOP_K` stays at 5 — no retrieval code changes in this plan.
