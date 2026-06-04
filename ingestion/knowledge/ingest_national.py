"""CLI: ingest the curated official national admission regulations.

    python -m ingestion.knowledge.ingest_national
Each curated URL (datafiles.chinhphu.vn signed PDF) is ingested via
KnowledgePipeline.run_for_url under the national scope (school="MOET",
document_type="national_regulation"). Idempotent: unchanged URLs skip
on content_hash. One bad URL never aborts the rest."""
import logging

from ingestion.knowledge.national_sources import load_national_sources
from ingestion.knowledge.pipeline import KnowledgePipeline
from services.knowledge.scope import NATIONAL_DOCUMENT_TYPE, NATIONAL_SCHOOL

logger = logging.getLogger(__name__)


def ingest_sources(sources, pipe):
    """Ingest every curated row via `pipe.run_for_url` under the national scope.
    Returns [(label, url)] where label is OK / SKIP / FAIL. One failure never
    aborts the rest."""
    results = []
    for s in sources:
        url = s["url"]
        try:
            result = pipe.run_for_url(
                url, school=NATIONAL_SCHOOL, document_type=NATIONAL_DOCUMENT_TYPE
            )
        except Exception as exc:  # one bad URL must not abort the batch
            logger.error("national ingest failed %s: %r", url, exc)
            results.append(("FAIL", url))
            continue
        results.append(("SKIP" if result.skipped else "OK", url))
    return results
