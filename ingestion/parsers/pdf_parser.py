                       
"""
Improved PDF parser with table extraction and scanned PDF detection.
"""

import os
import logging
import tempfile
from typing import Optional

from pdfminer.high_level import extract_text

from ingestion.models.pipeline_models import ParsedContent, DocumentType

logger = logging.getLogger(__name__)


def parse_pdf(content: bytes, url: str = "") -> ParsedContent:
    """
    Parse a text-based PDF into structured content.

    Args:
        content: Raw PDF bytes
        url: Source URL (for logging)

    Returns:
        ParsedContent with extracted text
    """
    with tempfile.NamedTemporaryFile(
        delete=False, suffix=".pdf"
    ) as f:
        f.write(content)
        path = f.name

    try:
        text = extract_text(path)

                                               
        tables = _extract_pdf_tables(path)

        parsed = ParsedContent(
            text=text,
            tables=tables,
            document_type=DocumentType.PDF_TEXT,
            parser_used="pdf_parser",
        )

        logger.info(
            f"Parsed PDF: {len(text)} chars, {len(tables)} tables"
        )
        return parsed

    finally:
        os.unlink(path)


def _extract_pdf_tables(path: str) -> list:
    """Try to extract tables from PDF using tabula-py."""
    try:
        import tabula

        dfs = tabula.read_pdf(
            path,
            pages="all",
            multiple_tables=True,
            silent=True,
        )

        tables = []
        for df in dfs:
            rows = []
                    
            rows.append(list(df.columns))
                  
            for _, row in df.iterrows():
                rows.append([str(v) for v in row.values])
            tables.append(rows)

        return tables

    except ImportError:
        logger.debug("tabula-py not installed, skipping table extraction")
        return []
    except Exception as e:
        logger.warning(f"PDF table extraction failed: {e}")
        return []