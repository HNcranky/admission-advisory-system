"""CLI: ingest the PDFs you marked status=keep in the crawl manifest.

    python -m ingestion.knowledge.ingest_manifest
Each kept URL is ingested via KnowledgePipeline.run_for_url (hybrid OCR);
on success/skip its status becomes 'done', on failure it stays 'keep' to retry.
"""
import logging

from ingestion.knowledge.crawl import DEFAULT_MANIFEST
from ingestion.knowledge.crawler.manifest import load_manifest, save_manifest
from ingestion.knowledge.pipeline import KnowledgePipeline

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


def _main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Ingest PDFs marked status=keep in the crawl manifest"
    )
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    entries = load_manifest(args.manifest)
    if not any(e.status == "keep" for e in entries):
        print(f"No entries with status=keep in {args.manifest}. "
              "Edit the manifest (set status=keep) first.")
        return 0

    results = ingest_keep_entries(entries, KnowledgePipeline())
    save_manifest(args.manifest, entries)

    for label, url in results:
        print(f"{label:<5} {url}")
    ok = sum(1 for s, _ in results if s == "OK")
    skipped = sum(1 for s, _ in results if s == "SKIP")
    failed = sum(1 for s, _ in results if s == "FAIL")
    print(f"Done: {len(results)} processed (ok={ok} skip={skipped} fail={failed})")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
