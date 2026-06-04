"""CLI: discover PDFs per school into a reviewable manifest.

    python -m ingestion.knowledge.crawl --school HUST
    python -m ingestion.knowledge.crawl --all
Then edit data/knowledge/manifest.json (set status keep/skip) and run
`python -m ingestion.knowledge.ingest_manifest` (plan 4).
"""
import logging
from pathlib import Path

from ingestion.fetchers.http_fetcher import http_fetch
from ingestion.knowledge.crawler.config import load_targets
from ingestion.knowledge.crawler.manifest import (
    load_manifest, mark_already_ingested, merge_candidates, save_manifest,
)
from ingestion.knowledge.crawler.pdf_crawler import crawl_target
from ingestion.knowledge.crawler.robots import build_robots_checker

logger = logging.getLogger(__name__)

DEFAULT_MANIFEST = Path("data/knowledge/manifest.json")


def build_manifest(targets, existing, *, crawl, doc_repo, discovered_at,
                   sitemap=True):
    """Crawl every target (one failure never aborts the rest), merge into the
    existing manifest, and flag already-ingested URLs."""
    candidates = []
    for t in targets:
        try:
            candidates.extend(crawl(t, sitemap=sitemap))
        except Exception as exc:  # one bad target must not abort the run
            logger.error("crawl failed for %s: %r", t.school, exc)
    merged = merge_candidates(existing, candidates, discovered_at=discovered_at)
    mark_already_ingested(merged, doc_repo)
    return merged


def _main(argv=None) -> int:
    import argparse
    from datetime import date

    from services.knowledge.repository import KnowledgeDocumentRepository

    parser = argparse.ArgumentParser(description="Discover admission PDFs into a manifest")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--school", help="crawl one school, e.g. HUST")
    group.add_argument("--all", action="store_true", help="crawl all configured schools")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--no-sitemap", action="store_true",
                        help="skip sitemap.xml discovery")
    parser.add_argument("--ignore-robots", action="store_true",
                        help="do not consult robots.txt")
    parser.add_argument("--delay", type=float, default=0.0,
                        help="seconds to sleep between page fetches")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    targets = load_targets()
    if args.school:
        targets = [t for t in targets if t.school == args.school]
        if not targets:
            parser.error(f"no crawl target configured for school {args.school!r}")

    existing = load_manifest(args.manifest)
    checker = build_robots_checker(fetch=http_fetch, respect=not args.ignore_robots)

    def crawl(target, sitemap=True):
        return crawl_target(target, sitemap=sitemap, allowed=checker,
                            delay=args.delay)

    merged = build_manifest(
        targets, existing, crawl=crawl,
        doc_repo=KnowledgeDocumentRepository(),
        discovered_at=date.today().isoformat(), sitemap=not args.no_sitemap,
    )
    save_manifest(args.manifest, merged)

    new_count = len(merged) - len(existing)
    pending = sum(1 for e in merged if e.status == "pending")
    already = sum(1 for e in merged if e.already_ingested)
    print(f"Manifest: {args.manifest}")
    print(f"  total={len(merged)}  new={new_count}  pending={pending}  "
          f"already_ingested={already}")
    print("Review the manifest (set status keep/skip), then run "
          "`python -m ingestion.knowledge.ingest_manifest`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
