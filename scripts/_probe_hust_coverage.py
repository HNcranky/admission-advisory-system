"""
Probe-only diagnostic: dump every unique program_name and admission_method_raw
emitted by both HUST sources, then check how the current dictionaries map them.

Used by Plan 04 Task 1.
"""
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
from ingestion.normalization.method_mapper import map_method


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

per_source_program_names = {}
per_source_method_raws = {}
per_source_combos = {}

for source in sources:
    facts = collect_facts(source)
    names = sorted({(f.program_name or "").strip() for f in facts if (f.program_name or "").strip()})
    methods = sorted({(f.admission_method_raw or "").strip() for f in facts if (f.admission_method_raw or "").strip()})
    combos_all = set()
    for f in facts:
        for c in (f.subject_combinations_raw or []):
            combos_all.add(c.strip())
    per_source_program_names[source.source_id] = names
    per_source_method_raws[source.source_id] = methods
    per_source_combos[source.source_id] = sorted(combos_all)

print("=" * 80)
print("UNIQUE PROGRAM NAMES PER SOURCE")
print("=" * 80)
for sid, names in per_source_program_names.items():
    print(f"\n--- {sid} ({len(names)} unique) ---")
    for n in names:
        print(f"  {n!r}")

print()
print("=" * 80)
print("UNIQUE admission_method_raw PER SOURCE")
print("=" * 80)
for sid, methods in per_source_method_raws.items():
    print(f"\n--- {sid} ({len(methods)} unique) ---")
    for m in methods:
        print(f"  {m!r}")

print()
print("=" * 80)
print("UNIQUE subject_combinations_raw PER SOURCE")
print("=" * 80)
for sid, combos in per_source_combos.items():
    print(f"\n--- {sid} ({len(combos)} unique) ---")
    print(f"  {combos}")

print()
print("=" * 80)
print("PROGRAM-NAME COVERAGE (per source, school_id='hust')")
print("=" * 80)
all_missing = {}
for sid, names in per_source_program_names.items():
    print(f"\n--- {sid} ---")
    missing = []
    for n in names:
        pid, canonical = map_program(n, school_id="hust")
        status = "OK" if pid else "MISSING"
        if not pid:
            missing.append(n)
        print(f"  [{status}] {n!r} -> pid={pid!r}  canon={canonical!r}")
    all_missing[sid] = missing
    print(f"  ({len(missing)} missing)")

print()
print("=" * 80)
print("METHOD COVERAGE (unique tokens after splitting on ';')")
print("=" * 80)
all_method_tokens = set()
for sid, methods in per_source_method_raws.items():
    for combined in methods:
        for tok in combined.split(";"):
            tok = tok.strip()
            if tok:
                all_method_tokens.add(tok)

KNOWN = {"thpt_score", "school_record", "talent_admission", "combined", "competency_test"}
unmapped_tokens = []
for tok in sorted(all_method_tokens):
    result = map_method(tok, school_id="hust")
    parts = [p.strip() for p in (result or "").split(";")]
    mapped_ok = bool(parts) and all(p in KNOWN for p in parts if p)
    status = "OK" if mapped_ok else "UNMAPPED"
    if not mapped_ok:
        unmapped_tokens.append(tok)
    print(f"  [{status}] {tok!r} -> {result!r}")

print()
print("=" * 80)
print("SUMMARY")
print("=" * 80)
for sid, missing in all_missing.items():
    print(f"  {sid}: {len(missing)} missing program names")
print(f"  {len(unmapped_tokens)} unmapped method tokens")

print()
print("MISSING PROGRAM NAMES UNION:")
union_missing = sorted({n for ms in all_missing.values() for n in ms})
for n in union_missing:
    print(f"  {n!r}")

print()
print("UNMAPPED METHOD TOKENS:")
for t in unmapped_tokens:
    print(f"  {t!r}")
