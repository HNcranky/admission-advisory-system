"""Verify HUST sources appear in the registry alongside VNU-UET."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.pipeline.ingestion_pipeline import IngestionPipeline

pipeline = IngestionPipeline()

hust_sources = pipeline.registry.get_sources_by_school("hust")
vnu_uet_sources = pipeline.registry.get_sources_by_school("vnu_uet")

print(f"HUST sources: {len(hust_sources)}")
for s in hust_sources:
    print(f"  {s.source_id:40s}  type={s.source_type:20s}  trust={s.trust_level}  active={s.active}")

print(f"\nVNU-UET sources (must remain intact): {len(vnu_uet_sources)}")
for s in vnu_uet_sources:
    print(f"  {s.source_id:40s}  type={s.source_type:20s}  trust={s.trust_level}  active={s.active}")

assert len(hust_sources) >= 2, f"Expected >=2 HUST sources, got {len(hust_sources)}"
source_types = {s.source_type for s in hust_sources}
assert "program_listing" in source_types, "Missing program_listing source for HUST"

second_source_types = source_types - {"program_listing"}
assert second_source_types, "Missing the chosen Source #2 (news_listing — 2026 announcement HTML)"

assert len(vnu_uet_sources) >= 2, "VNU-UET entries were lost — DO NOT overwrite the seed file"
print("\nPASS")
