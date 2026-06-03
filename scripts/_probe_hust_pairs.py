"""Build (program_code -> program_name) pairs across HUST's two sources."""
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
from ingestion.models.pipeline_models import SourceReference
from ingestion.normalization.program_mapper import map_program


def collect_facts(source):
    fetch_result = dispatch_fetch(source.root_url, source)
    doc_type = route_document(fetch_result)
    parsed = dispatch_parser(fetch_result, doc_type, source)
    if isinstance(parsed, list):
        return parsed
    source_ref = SourceReference(
        source_id=source.source_id,
        source_url=source.root_url,
        school_id=source.school_id,
        trust_level=source.trust_level,
    )
    return extract_admission_facts(parsed, source_ref, source.school_name)


pipeline = IngestionPipeline()
sources = pipeline.registry.get_sources_by_school("hust")

source_facts = {}
for s in sources:
    source_facts[s.source_id] = collect_facts(s)

ids = list(source_facts.keys())
assert len(ids) == 2, f"Expected 2 HUST sources, got {ids}"
sid_a, sid_b = ids

a_by_code = {}
for f in source_facts[sid_a]:
    if f.program_code:
        a_by_code.setdefault(f.program_code, []).append(f.program_name)
b_by_code = {}
for f in source_facts[sid_b]:
    if f.program_code:
        b_by_code.setdefault(f.program_code, []).append(f.program_name)

common = sorted(set(a_by_code) & set(b_by_code))
only_a = sorted(set(a_by_code) - set(b_by_code))
only_b = sorted(set(b_by_code) - set(a_by_code))

print(f"Source A: {sid_a}  ({len(a_by_code)} unique codes)")
print(f"Source B: {sid_b}  ({len(b_by_code)} unique codes)")
print(f"Common codes: {len(common)}")
print(f"Only A: {only_a}")
print(f"Only B: {only_b}")
print()
print("=" * 80)
print("CROSS-SOURCE PAIRS (by program_code)")
print("=" * 80)
mismatches = []
for code in common:
    name_a = a_by_code[code][0]
    name_b = b_by_code[code][0]
    pid_a, can_a = map_program(name_a, school_id="hust")
    pid_b, can_b = map_program(name_b, school_id="hust")
    match = pid_a == pid_b and pid_a is not None
    status = "MATCH" if match else "MISMATCH"
    if not match:
        mismatches.append((code, name_a, name_b, pid_a, pid_b))
    print(f"  [{status}] code={code}")
    print(f"    A: {name_a!r} -> {pid_a!r}")
    print(f"    B: {name_b!r} -> {pid_b!r}")

print()
print("=" * 80)
print(f"MISMATCH SUMMARY: {len(mismatches)} codes")
print("=" * 80)
for code, a, b, pa, pb in mismatches:
    print(f"  {code}: A({pa}) vs B({pb})")
    print(f"     A name: {a!r}")
    print(f"     B name: {b!r}")
