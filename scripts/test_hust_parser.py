"""
Diagnostic: run the pipeline fetch+parse step for each HUST source
and print extracted facts. Use this to evaluate parser output quality.
"""
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from ingestion.pipeline.ingestion_pipeline import IngestionPipeline
from ingestion.fetchers.fetch_dispatcher import dispatch_fetch
from ingestion.router.document_router import route_document
from ingestion.parsers.parser_dispatcher import dispatch_parser
from ingestion.extractors.admission_extractor import extract_admission_facts
from ingestion.models.pipeline_models import ExtractedAdmissionFact

pipeline = IngestionPipeline()
sources = pipeline.registry.get_sources_by_school("hust")

for source in sources:
    print(f"\n{'='*60}")
    print(f"Source: {source.source_id}")
    print(f"Profile: {source.parser_profile}")
    print(f"URL: {source.root_url}")

    try:
        fetch_result = dispatch_fetch(source.root_url, source)
        doc_type = route_document(fetch_result)
        print(f"Doc type: {doc_type}")

        parsed = dispatch_parser(fetch_result, doc_type, source)

        if isinstance(parsed, list):
            facts = parsed
            print(f"Specialized parser returned {len(facts)} facts directly")
        else:
            print(f"Generic parser returned text ({len(parsed.text)} chars)")
            from ingestion.models.pipeline_models import SourceReference
            source_ref = SourceReference(
                source_id=source.source_id,
                source_url=source.root_url,
                school_id=source.school_id,
                trust_level=source.trust_level,
            )
            facts = extract_admission_facts(parsed, source_ref, source.school_name)
            print(f"Extractor produced {len(facts)} facts")

        print(f"\nSample facts (first 5):")
        for fact in facts[:5]:
            print(f"  program_name={fact.program_name!r}")
            print(f"  program_code={fact.program_code!r}")
            print(f"  quota_raw={fact.quota_raw!r}")
            print(f"  method_raw={fact.admission_method_raw!r}")
            print(f"  combos={fact.subject_combinations_raw}")
            print()

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback; traceback.print_exc()
