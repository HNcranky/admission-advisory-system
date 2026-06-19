import json
from pathlib import Path

from ingestion.knowledge.registry.models import KnowledgeSource

SEEDS = (Path(__file__).resolve().parents[3]
         / "ingestion/knowledge/registry/seeds/knowledge_sources.json")


def _load():
    raw = json.loads(SEEDS.read_text(encoding="utf-8"))
    return [KnowledgeSource(**d) for d in raw]


def test_all_seeds_validate():
    # KnowledgeSource(**d) raises on a bad topic/document_type.
    assert _load(), "seed file empty or unparseable"


def test_new_school_program_overview_seeds_have_canonical_program():
    srcs = _load()
    new = [s for s in srcs
           if s.topic == "program_overview" and s.school in ("NEU", "VNU-UET")]
    assert new, "expected NEU/VNU-UET program_overview seeds"
    for s in new:
        assert s.program and s.program.strip(), \
            f"{s.source_url}: program_overview seed must set canonical program"
        assert s.chunk_strategy == "by_section", \
            f"{s.source_url}: program_overview must use by_section"
        assert s.document_type == "program_overview_page", s.source_url
