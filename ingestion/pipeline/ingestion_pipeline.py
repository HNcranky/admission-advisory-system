                                
"""
Main ingestion pipeline orchestrator.

Flow:
  Source Registry → Fetch → Document Router → Parser → Extractor → Normalizer

All stages are school-agnostic; school-specific behavior is driven by:
1. source.parser_profile → ParserRegistry plugin lookup
2. source.school_id → school-aware normalization dictionaries
3. combo_method_rules.json → data-driven method inference
"""

import json
import logging
from pathlib import Path
from typing import List, Optional, Union

from ingestion.registry.models import SourceEntry
from ingestion.registry.source_registry import SourceRegistry
from ingestion.fetchers.http_fetcher import http_fetch
from ingestion.fetchers.fetch_dispatcher import dispatch_fetch
from ingestion.router.document_router import route_document
from ingestion.parsers.parser_dispatcher import dispatch_parser
from ingestion.extractors.admission_extractor import extract_admission_facts
from ingestion.normalization.normalizer import normalize_facts
from ingestion.models.pipeline_models import (
    FetchResult,
    DocumentType,
    ParsedContent,
    ExtractedAdmissionFact,
    NormalizedAdmissionRecord,
    SourceReference,
)

logger = logging.getLogger(__name__)


class IngestionPipeline:
    """
    Orchestrates the full ingestion pipeline from source to normalized records.
    """

    def __init__(self, registry: Optional[SourceRegistry] = None):
        if registry is None:
            seed_path = (
                Path(__file__).parent.parent
                / "registry" / "seeds" / "initial_sources.json"
            )
            registry = SourceRegistry(seed_path=seed_path)
        self.registry = registry

    def run_for_source(
        self,
        source: SourceEntry,
        url: Optional[str] = None,
    ) -> List[NormalizedAdmissionRecord]:
        """
        Run the full pipeline for a single source.

        Args:
            source: Source configuration
            url: Override URL (defaults to source.root_url)

        Returns:
            List of normalized admission records
        """
        target_url = url or source.root_url
        logger.info(
            f"Starting pipeline for source '{source.source_id}' "
            f"(school={source.school_id}) URL: {target_url}"
        )

                                                                  
        logger.info("Step 1: Fetching content...")
        fetch_result = dispatch_fetch(target_url, source)
        logger.info(
            f"  Fetched: {fetch_result.http_status}, "
            f"{len(fetch_result.raw_content)} bytes, "
            f"type={fetch_result.content_type}"
        )

                                                                  
        logger.info("Step 2: Routing document...")
        doc_type = route_document(fetch_result)
        logger.info(f"  Routed to: {doc_type}")

                                                                  
        logger.info("Step 3: Parsing content...")
        parse_result = dispatch_parser(
            fetch_result, doc_type, source
        )

                                                            
                                                                
        if isinstance(parse_result, list) and parse_result and isinstance(
            parse_result[0], ExtractedAdmissionFact
        ):
            extracted_facts = parse_result
            logger.info(
                f"  Specialized parser returned "
                f"{len(extracted_facts)} facts"
            )
        elif isinstance(parse_result, ParsedContent):
            logger.info(
                f"  Parsed: {len(parse_result.text)} chars, "
                f"{len(parse_result.tables)} tables"
            )

                                                                  
            logger.info("Step 4: Extracting admission facts...")
            source_ref = SourceReference(
                source_id=source.source_id,
                source_url=target_url,
                school_id=source.school_id,
                trust_level=source.trust_level,
            )
            extracted_facts = extract_admission_facts(
                parsed=parse_result,
                source_ref=source_ref,
                school_name=source.school_name,
            )
            logger.info(
                f"  Extracted {len(extracted_facts)} facts"
            )
        else:
            logger.warning("  Parser returned unexpected type")
            extracted_facts = []

        if not extracted_facts:
            logger.warning("No facts extracted, pipeline complete")
            return []

                                                                  
        logger.info("Step 5: Normalizing facts...")
        records = normalize_facts(
            extracted_facts,
            school_id=source.school_id,
        )
        logger.info(f"  Normalized {len(records)} records")

                             
        self.registry.update_last_fetched(source.source_id)

        return records

    def run_for_school(
        self, school_id: str
    ) -> List[NormalizedAdmissionRecord]:
        """
        Run pipeline for all sources of a school.

        Args:
            school_id: School identifier (e.g. "hust")

        Returns:
            All normalized records from all sources
        """
        sources = self.registry.get_sources_by_school(school_id)
        if not sources:
            logger.warning(f"No sources found for school: {school_id}")
            return []

        all_records = []
        for source in sources:
            if not source.active:
                continue
            try:
                records = self.run_for_source(source)
                all_records.extend(records)
            except Exception as e:
                logger.error(
                    f"Pipeline failed for source "
                    f"'{source.source_id}': {e}"
                )

        logger.info(
            f"School '{school_id}': "
            f"{len(all_records)} total records "
            f"from {len(sources)} sources"
        )
        return all_records

    def run_all_schools(self) -> List[NormalizedAdmissionRecord]:
        """
        Run pipeline for all active sources across all schools.

        Returns:
            All normalized records from all schools
        """
        sources = self.registry.get_sources_for_crawl()
        school_ids = sorted(set(s.school_id for s in sources))

        logger.info(
            f"Running pipeline for {len(school_ids)} schools: "
            f"{', '.join(school_ids)}"
        )

        all_records = []
        for school_id in school_ids:
            try:
                records = self.run_for_school(school_id)
                all_records.extend(records)
            except Exception as e:
                logger.error(
                    f"Pipeline failed for school '{school_id}': {e}"
                )

        return all_records

    def list_schools(self) -> List[dict]:
        """
        List all schools with their source counts.

        Returns:
            List of dicts with school_id, school_name, source_count, active_count
        """
        all_sources = self.registry.all_sources()
        schools = {}
        for s in all_sources:
            if s.school_id not in schools:
                schools[s.school_id] = {
                    "school_id": s.school_id,
                    "school_name": s.school_name,
                    "total_sources": 0,
                    "active_sources": 0,
                }
            schools[s.school_id]["total_sources"] += 1
            if s.active:
                schools[s.school_id]["active_sources"] += 1

        return list(schools.values())

    def run_single_url(
        self,
        url: str,
        parser_profile: str = "default",
    ) -> List[NormalizedAdmissionRecord]:
        """
        Run pipeline for a single URL (legacy compatibility).

        Args:
            url: URL to process
            parser_profile: Parser profile to use

        Returns:
            Normalized records
        """
                                   
        temp_source = SourceEntry(
            source_id="temp",
            school_id="unknown",
            school_name="Unknown",
            source_type="admission_homepage",
            root_url=url,
            parser_profile=parser_profile,
        )
        return self.run_for_source(temp_source)


                                                                  

def run_ingestion(url: str):
    """Legacy entry point for backwards compatibility."""
    pipeline = IngestionPipeline()
    records = pipeline.run_single_url(url)
    return records