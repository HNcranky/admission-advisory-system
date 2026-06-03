from services.knowledge.models import KnowledgeChunk, ScoredChunk


def test_knowledge_chunk_minimal_requires_only_school_and_text():
    chunk = KnowledgeChunk(school="VNU-UET", chunk_text="Học phí 2024...")
    assert chunk.school == "VNU-UET"
    assert chunk.topic is None
    assert chunk.embedding is None


def test_scored_chunk_extends_knowledge_chunk_with_score():
    scored = ScoredChunk(school="HUST", chunk_text="x", score=0.87)
    assert isinstance(scored, KnowledgeChunk)
    assert scored.score == 0.87


from services.knowledge.models import KnowledgeDocument


def test_knowledge_document_defaults():
    doc = KnowledgeDocument(
        school="HUST",
        document_type="tuition_page",
        source_url="https://x/tuition",
    )
    assert doc.content_hash is None
    assert doc.raw_text is None
    assert doc.id is None


from services.knowledge.models import Citation, KnowledgeQAResult


def test_citation_carries_source_url_and_chunk_text():
    c = Citation(source_url="https://uet/hoc-phi", chunk_text="Học phí 35 triệu")
    assert c.source_url == "https://uet/hoc-phi"
    assert c.chunk_text == "Học phí 35 triệu"


def test_knowledge_qa_result_no_data_defaults():
    r = KnowledgeQAResult(has_data=False)
    assert r.has_data is False
    assert r.answer is None
    assert r.citations == []
    assert r.confidence == 0.0


def test_knowledge_qa_result_with_answer_and_citations():
    r = KnowledgeQAResult(
        has_data=True,
        answer="Học phí khoảng 35 triệu/năm.",
        citations=[Citation(source_url="u", chunk_text="t")],
        confidence=0.91,
    )
    assert r.has_data is True
    assert r.answer.startswith("Học phí")
    assert len(r.citations) == 1
    assert r.confidence == 0.91
