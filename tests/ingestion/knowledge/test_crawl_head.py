from ingestion.knowledge.crawler.pdf_crawler import parse_head_headers


def test_parse_head_headers_extracts_fields():
    out = parse_head_headers({
        "Content-Type": "application/pdf",
        "Content-Length": "12345",
        "Last-Modified": "Mon, 01 Mar 2026 00:00:00 GMT",
    })
    assert out == {
        "content_type": "application/pdf",
        "size_bytes": 12345,
        "last_modified": "Mon, 01 Mar 2026 00:00:00 GMT",
    }


def test_parse_head_headers_handles_missing_and_bad_length():
    out = parse_head_headers({"Content-Length": "not-a-number"})
    assert out == {"content_type": None, "size_bytes": None, "last_modified": None}
