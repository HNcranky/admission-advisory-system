from ingestion.knowledge.chunker import chunk_text

# Three blank-line blocks → size strategy would keep them whole here anyway,
# but whole_page must collapse them into exactly one chunk regardless of blocks.
MULTI_BLOCK = "Block one.\n\n" + ("Block two. " * 30) + "\n\n" + ("Block three. " * 30)


def test_size_strategy_matches_default_split():
    chunks = chunk_text(MULTI_BLOCK, strategy="size")
    # the default size splitter may produce >1 chunk for this text
    assert len(chunks) >= 1
    assert all(c.chunk_text for c in chunks)


def test_whole_page_yields_single_chunk():
    chunks = chunk_text(MULTI_BLOCK, strategy="whole_page")
    assert len(chunks) == 1
    assert chunks[0].chunk_text == MULTI_BLOCK.strip()
    assert chunks[0].span_start == 0


def test_whole_page_empty_text_yields_nothing():
    assert chunk_text("   ", strategy="whole_page") == []


def test_whole_page_oversized_falls_back_to_size_split():
    big = ("Cau van rat dai. " * 1000)  # ~17k chars, over the 8000 cap
    chunks = chunk_text(big, strategy="whole_page", max_chars=8000)
    assert len(chunks) > 1
    assert all(len(c.chunk_text) <= 1800 + 256 for c in chunks)


def test_unknown_strategy_defaults_to_size():
    chunks = chunk_text(MULTI_BLOCK, strategy="bogus")
    assert chunks == chunk_text(MULTI_BLOCK, strategy="size")


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
