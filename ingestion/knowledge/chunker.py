import re
from dataclasses import dataclass

from ingestion.config.settings import (
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    WHOLE_PAGE_MAX_CHARS,
)

# Blank-line block boundary (also matches the line before a "[Trang N]" marker
# because markers are emitted preceded by a blank line in pdf_pages.py).
_BLOCK_SEP = re.compile(r"\n[ \t]*\n")
# Sentence-ish cut points for hard-splitting an oversized single block.
_SENTENCE_END = re.compile(r"[.!?。]\s|\n")
# Markdown section heading emitted by the HTML parser's _to_markdown.
_SECTION_HEADING = re.compile(r"(?m)^##\s+(.+?)\s*$")


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


def chunk_text(
    text: str,
    strategy: str = "size",
    *,
    context_label: str | None = None,
    size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
    max_chars: int = WHOLE_PAGE_MAX_CHARS,
) -> list[Chunk]:
    """Dispatch chunking by strategy.

    - "by_section": split on '## ' headings; each section becomes a chunk with a
      '{context_label} — {section_title}' header so program identity and topic
      live in the embedding. Oversized sections sub-split, header on each part.
    - "whole_page": emit the whole text as ONE chunk (good for short, self-
      contained pages like program overviews). Pages longer than ``max_chars``
      fall back to size-based splitting so a single embed call never exceeds the
      embedding model's input limit.
    - anything else ("size", default): the structure-aware size splitter.
    """
    if strategy == "by_section":
        return chunk_by_section(text, context_label, size=size, overlap=overlap)
    if strategy == "whole_page":
        body = text.strip()
        if not body:
            return []
        if len(body) <= max_chars:
            return [Chunk(chunk_text=body, span_start=0, span_end=len(body))]
        # too large for one embedding — degrade to size split rather than risk
        # silent truncation of the page tail.
        return split_into_chunks(text, size, overlap)
    return split_into_chunks(text, size, overlap)


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
        next_start = end - overlap
        if next_start <= start:
            # The chunk was no larger than the overlap (a short block boundary
            # or reused cut point). Overlapping would re-emit nearly the same
            # text and crawl forward one char at a time, so skip past it.
            next_start = end
        start = next_start

    return chunks
