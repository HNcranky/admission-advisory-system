                   
"""
Entry point for the ingestion pipeline.

Usage:
    python -m ingestion.main                      # List available schools
    python -m ingestion.main --school hust        # Run for all HUST sources
    python -m ingestion.main --source <id>        # Run for a specific source
    python -m ingestion.main --url <url>          # Run for a single URL
    python -m ingestion.main --all                # Run for all active schools
    python -m ingestion.main --list-schools       # List schools and sources
"""

import sys
import json
import logging
import argparse
import unicodedata
from pathlib import Path

                                      
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from ingestion.pipeline.ingestion_pipeline import IngestionPipeline
from ingestion.registry.source_registry import SourceRegistry
from ingestion.storage.db_writer import save_canonical_records

                   
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ingestion")


def main():
    parser = argparse.ArgumentParser(
        description="Admission Data Ingestion Pipeline"
    )
    parser.add_argument(
        "--school",
        type=str,
        help="School ID to crawl all sources (e.g. 'hust', 'neu', 'uet', 'ftu')",
    )
    parser.add_argument(
        "--source",
        type=str,
        help="Specific source ID to crawl",
    )
    parser.add_argument(
        "--url",
        type=str,
        help="Single URL to process",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run for all active sources across all schools",
    )
    parser.add_argument(
        "--list-schools",
        action="store_true",
        help="List all registered schools and their sources",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON file path",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    pipeline = IngestionPipeline()

                                                                  
    if args.list_schools:
        _print_schools(pipeline)
        return

    records = []

    if args.url:
        logger.info(f"Processing single URL: {args.url}")
        records = pipeline.run_single_url(args.url)

    elif args.source:
        source = pipeline.registry.get_source(args.source)
        if source:
            logger.info(f"Processing source: {args.source}")
            records = pipeline.run_for_source(source)
        else:
            logger.error(f"Source not found: {args.source}")
            sys.exit(1)

    elif args.school:
        logger.info(f"Processing school: {args.school}")
        records = pipeline.run_for_school(args.school)

    elif args.all:
        logger.info("Processing ALL active sources")
        records = pipeline.run_all_schools()

    else:
                                         
        print("\nAdmission Data Ingestion Pipeline")
        print("=" * 50)
        print("\nNo action specified. Available options:\n")
        _print_schools(pipeline)
        print("\nRun with --help for full usage.\n")
        return

                                                                  
    logger.info(f"\n{'='*60}")
    logger.info(f"Pipeline complete: {len(records)} normalized records")
    logger.info(f"{'='*60}")

    if records:
        saved = save_canonical_records(records)
        logger.info(f"Saved/updated {saved} records in canonical_admission_records")

               
    output_data = []
    for record in records:
        output_data.append(record.model_dump(
            mode="json",
            exclude_none=True,
        ))

                   
    for i, record in enumerate(records):
        logger.info(
            f"\n[{i+1}] {record.program_name_raw or 'N/A'} "
            f"({record.program_id or 'N/A'})"
        )
        if record.program_name_canonical:
            logger.info(
                f"    -> Canonical: {record.program_name_canonical}"
            )
        if record.admission_method:
            logger.info(f"    Method: {record.admission_method}")
        if record.subject_combinations:
            combos = ", ".join(
                c.code for c in record.subject_combinations
            )
            logger.info(f"    Combos: {combos}")
        if record.quota:
            logger.info(f"    Quota: {record.quota.model_dump()}")

                               
    if args.output:
        output_path = Path(args.output)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        logger.info(f"\nSaved to: {output_path}")
    else:
                              
        print(json.dumps(output_data, ensure_ascii=False, indent=2))


def _print_schools(pipeline: IngestionPipeline):
    """Print table of available schools and sources."""
    schools = pipeline.list_schools()

    if not schools:
        print("  No schools registered.")
        return

    print(f"\n  {'School ID':<12} {'School Name':<35} {'Active':>7} {'Total':>7}")
    print(f"  {'-'*12} {'-'*35} {'-'*7} {'-'*7}")

    for s in schools:
        school_id = _ascii_text(s["school_id"])
        school_name = _ascii_text(s["school_name"])
        status = "active" if s["active_sources"] > 0 else "paused"
        print(
            f"  {school_id:<12} {school_name:<35} "
            f"{s['active_sources']:>5}   {s['total_sources']:>5}  {status}"
        )

    print(f"\n  Total: {len(schools)} schools registered")
    print(f"\n  Usage examples:")
    print(f"    python -m ingestion.main --school hust")
    print(f"    python -m ingestion.main --source hust_program_listing")
    print(f"    python -m ingestion.main --all")


def _ascii_text(value: object) -> str:
    """Return text safe for legacy Windows console encodings."""
    text = str(value).replace("\u0110", "D").replace("\u0111", "d")
    normalized = unicodedata.normalize("NFKD", text)
    return normalized.encode("ascii", errors="ignore").decode("ascii")


if __name__ == "__main__":
    main()
