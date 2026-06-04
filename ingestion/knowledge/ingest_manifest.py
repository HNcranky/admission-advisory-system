"""CLI: ingest the PDFs you marked status=keep in the crawl manifest.

    python -m ingestion.knowledge.ingest_manifest
Each kept URL is ingested via KnowledgePipeline.run_for_url (hybrid OCR);
on success/skip its status becomes 'done', on failure it stays 'keep' to retry.
"""
import logging

logger = logging.getLogger(__name__)


def ingest_keep_entries(entries, pipe):
    """Ingest every status=='keep' entry through `pipe.run_for_url`.
    Mutates each entry's status; returns [(label, url)] where label is
    OK / SKIP / FAIL. One failure never aborts the rest."""
    results = []
    for e in entries:
        if e.status != "keep":
            continue
        try:
            result = pipe.run_for_url(e.url, school=e.school)
        except Exception as exc:  # one bad URL must not abort the batch
            logger.error("ingest failed %s: %r", e.url, exc)
            results.append(("FAIL", e.url))
            continue
        e.status = "done"
        results.append(("SKIP" if result.skipped else "OK", e.url))
    return results
