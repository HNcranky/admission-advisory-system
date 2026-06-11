import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ingestion.knowledge.registry.knowledge_registry import KnowledgeRegistry


def test_default_seed_loads_registry_schools_each_with_sources():
    # The curated http registry seed covers HUST and VNU-UET. NEU is sourced from
    # local PDFs (data/knowledge/pdf_scanned/) instead — its official documents are
    # scanned and its public URLs were broken — so it is intentionally not in the
    # registry seed and is ingested via `pipeline --local-dir`.
    reg = KnowledgeRegistry()
    schools = reg.schools()
    assert set(schools) >= {"HUST", "VNU-UET"}
    for school in ("HUST", "VNU-UET"):
        sources = reg.get_sources_by_school(school)
        assert len(sources) >= 1, f"{school} has no sources"


def test_all_sources_returns_models():
    reg = KnowledgeRegistry()
    sources = reg.all_sources()
    assert len(sources) >= 6
    assert sources[0].topic in {
        "tuition", "curriculum", "scholarship", "dormitory",
        "career", "admission_policy", "program_overview",
    }


def test_custom_seed_path(tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps([
        {"school": "X", "source_url": "https://x/t",
         "document_type": "tuition_page", "topic": "tuition"},
    ]), encoding="utf-8")
    reg = KnowledgeRegistry(seed_path=seed)
    assert reg.schools() == ["X"]


def test_invalid_entry_in_seed_raises(tmp_path):
    seed = tmp_path / "bad.json"
    seed.write_text(json.dumps([
        {"school": "X", "source_url": "https://x/t",
         "document_type": "tuition_page", "topic": "BOGUS"},
    ]), encoding="utf-8")
    with pytest.raises(ValidationError):
        KnowledgeRegistry(seed_path=seed)
