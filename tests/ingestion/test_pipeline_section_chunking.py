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
