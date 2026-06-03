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


def test_no_chunk_explosion_when_block_boundary_smaller_than_overlap():
    """A short block (< overlap) before a long run must not trigger a
    1-char-per-step death spiral. Count stays proportional to length."""
    text = "A" * 50 + "\n\n" + "B" * 3000
    chunks = split_into_chunks(text, size=1800, overlap=256)
    assert len(chunks) < 20


def test_chunk_count_proportional_to_text_length():
    """~23k chars at size=1800/overlap=256 → stride ~1544 → ~15 chunks,
    never thousands (regression for the overlap death-spiral)."""
    text = "Một câu về tuyển sinh tài năng. " * 720  # ~23000 chars
    chunks = split_into_chunks(text, size=1800, overlap=256)
    assert len(chunks) <= 40


def test_page_marker_is_preserved_in_chunk_text():
    text = "[Trang 1]\nHọc phí.\n\n[Trang 2]\nHọc bổng."
    chunks = split_into_chunks(text, size=1800, overlap=256)
    joined = " ".join(c.chunk_text for c in chunks)
    assert "[Trang 1]" in joined
    assert "[Trang 2]" in joined
