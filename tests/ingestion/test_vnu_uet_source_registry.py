from pathlib import Path

from ingestion.registry.source_registry import SourceRegistry


SEED_PATH = (
    Path(__file__).parent.parent.parent
    / "ingestion"
    / "registry"
    / "seeds"
    / "initial_sources.json"
)


def test_vnu_uet_proposal_pdf_is_active_for_crawls_with_specialized_parser():
    registry = SourceRegistry(seed_path=SEED_PATH)

    source = registry.get_source("vnuhn_proposal_pdf_2026")
    assert source is not None
    assert source.active is True
    assert source.parser_profile == "vnu_uet_proposal_pdf"

    crawl_source_ids = {
        crawl_source.source_id
        for crawl_source in registry.get_sources_for_crawl()
    }
    assert "vnuhn_proposal_pdf_2026" in crawl_source_ids
    assert "vnu_uet_admission_homepage_2026" in crawl_source_ids
