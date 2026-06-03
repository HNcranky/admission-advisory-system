                           
"""
Document Router: classifies fetched content into the correct
DocumentType so the appropriate parser can be selected.
"""

import logging
from ingestion.models.pipeline_models import FetchResult, DocumentType

logger = logging.getLogger(__name__)

                                     
MAGIC_BYTES = {
    b"%PDF": DocumentType.PDF_TEXT,                              
    b"PK": DocumentType.DOCX,                                          
}

                                      
CONTENT_TYPE_MAP = {
    "application/pdf": DocumentType.PDF_TEXT,
    "application/msword": DocumentType.DOCX,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocumentType.DOCX,
    "text/html": DocumentType.HTML_ARTICLE,
    "application/xhtml+xml": DocumentType.HTML_ARTICLE,
    "image/jpeg": DocumentType.IMAGE,
    "image/png": DocumentType.IMAGE,
    "image/gif": DocumentType.IMAGE,
    "image/webp": DocumentType.IMAGE,
}

              
PDF_EXTENSIONS = (".pdf",)
DOCX_EXTENSIONS = (".docx", ".doc")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
FACEBOOK_DOMAINS = ("facebook.com", "fb.com", "fb.watch")


def route_document(fetch_result: FetchResult) -> DocumentType:
    """
    Classify a fetched document into a DocumentType.

    Classification priority:
    1. Content-Type header
    2. URL pattern analysis
    3. Content magic bytes
    4. Default to HTML

    Args:
        fetch_result: The fetched content with metadata

    Returns:
        The determined DocumentType
    """
    doc_type = DocumentType.UNKNOWN

                                                                  
    content_type = fetch_result.content_type.lower().split(";")[0].strip()

    if content_type in CONTENT_TYPE_MAP:
        doc_type = CONTENT_TYPE_MAP[content_type]
        logger.debug(
            f"Routed by Content-Type '{content_type}' → {doc_type}"
        )

                                                                  
    if doc_type == DocumentType.UNKNOWN:
        url_lower = fetch_result.final_url.lower()

        if any(url_lower.endswith(ext) for ext in PDF_EXTENSIONS):
            doc_type = DocumentType.PDF_TEXT
        elif any(url_lower.endswith(ext) for ext in DOCX_EXTENSIONS):
            doc_type = DocumentType.DOCX
        elif any(url_lower.endswith(ext) for ext in IMAGE_EXTENSIONS):
            doc_type = DocumentType.IMAGE
        elif any(domain in url_lower for domain in FACEBOOK_DOMAINS):
            doc_type = DocumentType.FACEBOOK_POST

        if doc_type != DocumentType.UNKNOWN:
            logger.debug(f"Routed by URL pattern → {doc_type}")

                                                                  
    if doc_type == DocumentType.UNKNOWN:
        raw = fetch_result.raw_content[:8]
        for magic, dtype in MAGIC_BYTES.items():
            if raw.startswith(magic):
                doc_type = dtype
                logger.debug(f"Routed by magic bytes → {doc_type}")
                break

                                                                  
    if doc_type == DocumentType.UNKNOWN:
        doc_type = DocumentType.HTML_ARTICLE
        logger.debug(f"Defaulting to {doc_type}")

                                                                  
    if doc_type == DocumentType.PDF_TEXT:
        doc_type = _refine_pdf_type(fetch_result)

    logger.info(
        f"Document routed: {fetch_result.final_url} → {doc_type}"
    )
    return doc_type


def _refine_pdf_type(fetch_result: FetchResult) -> DocumentType:
    """
    Determine if a PDF is text-based or scanned.

    Heuristic: try to extract text. If extracted text is
    very short relative to file size, it's likely scanned.
    """
    try:
        from pdfminer.high_level import extract_text
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".pdf"
        ) as f:
            f.write(fetch_result.raw_content)
            path = f.name

        try:
            text = extract_text(path)
            text_chars = len(text.strip())
            file_size = len(fetch_result.raw_content)

                                                                          
                                 
            if file_size > 10_000 and text_chars < 100:
                logger.debug(
                    f"PDF classified as scanned "
                    f"({text_chars} chars, {file_size} bytes)"
                )
                return DocumentType.PDF_SCANNED
            else:
                return DocumentType.PDF_TEXT
        finally:
            os.unlink(path)

    except Exception as e:
        logger.warning(f"PDF refinement failed: {e}, assuming text PDF")
        return DocumentType.PDF_TEXT
