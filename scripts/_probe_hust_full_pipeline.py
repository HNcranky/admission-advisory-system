"""Run the full normalize_facts path for both HUST sources (Plan 04 Task 5 Step 2)."""
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

from ingestion.pipeline.ingestion_pipeline import IngestionPipeline
from ingestion.fetchers.fetch_dispatcher import dispatch_fetch
from ingestion.router.document_router import route_document
from ingestion.parsers.parser_dispatcher import dispatch_parser
from ingestion.extractors.admission_extractor import extract_admission_facts
from ingestion.normalization.normalizer import normalize_facts
from ingestion.models.pipeline_models import SourceReference

pipeline = IngestionPipeline()
sources = pipeline.registry.get_sources_by_school("hust")

for source in sources:
    print(f"\n=== Source: {source.source_id} ===")
    fetch = dispatch_fetch(source.root_url, source)
    doc_type = route_document(fetch)
    parsed = dispatch_parser(fetch, doc_type, source)
    if isinstance(parsed, list):
        facts = parsed
    else:
        source_ref = SourceReference(
            source_id=source.source_id,
            source_url=source.root_url,
            school_id=source.school_id,
            trust_level=source.trust_level,
        )
        facts = extract_admission_facts(parsed, source_ref, source.school_name)
    records = normalize_facts(facts, school_id='hust')
    pid_non_null = sum(1 for r in records if r.program_id)
    method_non_null = sum(1 for r in records if r.admission_method)
    print(f"  {len(facts)} facts -> {len(records)} normalized records")
    print(f"  program_id non-null: {pid_non_null}/{len(records)}")
    print(f"  admission_method non-null: {method_non_null}/{len(records)}")
    for r in records[:5]:
        pid = r.program_id or 'NONE'
        pname = r.program_name_canonical or 'NONE'
        method = r.admission_method or 'NONE'
        quota_obj = r.quota
        quota_val = quota_obj.value if quota_obj else 'NONE'
        print(f"    pid={pid!r}  canon={pname!r}  method={method!r}  quota={quota_val}")
