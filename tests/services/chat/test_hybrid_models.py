from services.chat.hybrid_models import AdvisoryBlock, KnowledgeBlock


def test_advisory_block_defaults():
    b = AdvisoryBlock()
    assert b.has_data is False
    assert b.answer is None
    assert b.sources == []


def test_knowledge_block_defaults():
    b = KnowledgeBlock()
    assert b.has_data is False
    assert b.school is None
    assert b.topic is None
    assert b.answer is None
    assert b.sources == []


def test_knowledge_block_full():
    b = KnowledgeBlock(
        school="VNU-UET", topic="tuition", has_data=True,
        answer="35 triệu/năm", sources=["https://uet/hp"],
    )
    assert b.school == "VNU-UET"
    assert b.has_data is True
    assert b.sources == ["https://uet/hp"]
