                              
"""
Selects and runs the appropriate parser based on DocumentType
and parser_profile from the source registry.

Uses the ParserRegistry to look up specialized parsers,
falling back to generic parsers for standard document types.
"""

import logging
from typing import Optional, List, Union

from ingestion.models.pipeline_models import (
    DocumentType, ParsedContent, FetchResult, ExtractedAdmissionFact,
)
from ingestion.registry.models import SourceEntry
from ingestion.parsers.base_parser import ParserRegistry
from ingestion.parsers.html_parser import parse_html
from ingestion.parsers.pdf_parser import parse_pdf

logger = logging.getLogger(__name__)


def dispatch_parser(
    fetch_result: FetchResult,
    doc_type: DocumentType,
    source: SourceEntry,
) -> Union[ParsedContent, List[ExtractedAdmissionFact]]:
    """
    Dispatch to the appropriate parser based on document type
    and source configuration.

    For specialized parser profiles registered in ParserRegistry,
    the parser returns ExtractedAdmissionFact directly (skipping
    the generic extraction step).

    Args:
        fetch_result: Fetched content
        doc_type: Classified document type
        source: Source configuration (includes parser_profile, school_id, etc.)

    Returns:
        Either ParsedContent (for generic flow)
        or List[ExtractedAdmissionFact] (for specialized parsers)
    """
    parser_profile = source.parser_profile

                                                                  
    registry = ParserRegistry.get_instance()

    if registry.has(parser_profile):
        parser = registry.get(parser_profile)
        logger.info(
            f"Using specialized parser '{parser_profile}' "
            f"({parser.__class__.__name__})"
        )
        return parser.parse(
            content=fetch_result.raw_content,
            source_url=fetch_result.final_url,
            school_id=source.school_id,
            school_name=source.school_name,
            source_metadata=source.metadata,
        )

                                                                  
    if doc_type == DocumentType.HTML_ARTICLE:
        return parse_html(
            content=fetch_result.raw_content,
            url=fetch_result.final_url,
        )

    elif doc_type in (DocumentType.PDF_TEXT, DocumentType.PDF_SCANNED):
        if doc_type == DocumentType.PDF_SCANNED:
                                                   
            logger.warning(
                f"Scanned PDF detected for {fetch_result.final_url}, "
                "falling back to text extraction"
            )
        return parse_pdf(
            content=fetch_result.raw_content,
            url=fetch_result.final_url,
        )

    elif doc_type == DocumentType.DOCX:
                                     
        logger.warning("DOCX parsing not yet implemented")
        return ParsedContent(
            text="",
            document_type=doc_type,
            parser_used="none",
        )

    else:
        logger.warning(f"No parser for document type {doc_type}")
        return ParsedContent(
            text="",
            document_type=doc_type,
            parser_used="none",
        )
