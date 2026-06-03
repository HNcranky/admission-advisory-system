"""
Diagnostic: run the pipeline fetch+parse step for each VNU-UET source
and print extracted facts. Use this to evaluate parser output quality.
"""
import sys
import json
import logging
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.pipeline.ingestion_pipeline import IngestionPipeline
from ingestion.fetchers.fetch_dispatcher import dispatch_fetch
from ingestion.router.document_router import route_document
from ingestion.parsers.parser_dispatcher import dispatch_parser
from ingestion.extractors.admission_extractor import extract_admission_facts
from ingestion.models.pipeline_models import (
    ExtractedAdmissionFact,
    SourceReference,
)


TEXT_EXCERPT_CHARS = 500


def _extract_generic_facts(parsed, source, source_url):
    source_ref = SourceReference(
        source_id=source.source_id,
        source_url=source_url,
        school_id=source.school_id,
        trust_level=source.trust_level,
    )
    return extract_admission_facts(
        parsed=parsed,
        source_ref=source_ref,
        school_name=source.school_name,
    )


def _print_text_diagnostic(parsed):
    excerpt = " ".join(parsed.text.split())[:TEXT_EXCERPT_CHARS]
    print("No facts extracted; parsed text diagnostic:")
    print(f"  text_length={len(parsed.text)}")
    print(f"  excerpt={excerpt}")


def _print_fact_sample(facts):
    print("\nSample facts (first 3):")
    for fact in facts[:3]:
        if not isinstance(fact, ExtractedAdmissionFact):
            print(f"  Unexpected fact type: {type(fact).__name__}")
            continue

        print(f"  program_name={fact.program_name}")
        print(f"  quota_raw={fact.quota_raw}")
        print(f"  admission_method_raw={fact.admission_method_raw}")
        print(f"  subject_combinations_raw={fact.subject_combinations_raw}")
        print()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    pipeline = IngestionPipeline()
    sources = pipeline.registry.get_sources_by_school("vnu_uet")
    print(json.dumps({"vnu_uet_sources": len(sources)}, ensure_ascii=False))

    error_count = 0

    for source in sources:
        print(f"\n{'=' * 60}")
        print(f"Source id: {source.source_id}")
        print(f"Parser profile: {source.parser_profile}")
        print(f"Active: {getattr(source, 'active', None)}")
        print(f"URL: {source.root_url}")

        try:
            fetch_result = dispatch_fetch(source.root_url, source)
            doc_type = route_document(fetch_result)
            print(f"Doc type: {doc_type}")

            parsed = dispatch_parser(fetch_result, doc_type, source)

            if isinstance(parsed, list):
                facts = parsed
                valid_count = sum(
                    isinstance(fact, ExtractedAdmissionFact)
                    for fact in facts
                )
                print(
                    "Parser returned list "
                    f"({len(facts)} items, "
                    f"{valid_count} ExtractedAdmissionFact)"
                )
            else:
                print(
                    "Generic parser returned text "
                    f"({len(parsed.text)} chars)"
                )
                facts = _extract_generic_facts(
                    parsed,
                    source,
                    fetch_result.final_url,
                )
                print(f"Extractor produced {len(facts)} facts")
                if not facts:
                    _print_text_diagnostic(parsed)

            _print_fact_sample(facts)

        except Exception as e:
            error_count += 1
            print(f"ERROR: {e}")
            import traceback

            traceback.print_exc()

    if error_count:
        print(f"\nCompleted with {error_count} source error(s).")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
