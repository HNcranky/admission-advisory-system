"""Verify VNU-UET sources appear in the registry."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.pipeline.ingestion_pipeline import IngestionPipeline

pipeline = IngestionPipeline()
sources = pipeline.registry.get_sources_by_school("vnu_uet")

print(f"VNU-UET sources: {len(sources)}")
for s in sources:
    print(
        f"  {s.source_id:40s}  type={s.source_type:20s}  "
        f"trust={s.trust_level}  active={s.active}"
    )

assert len(sources) >= 2, f"Expected >=2 VNU-UET sources, got {len(sources)}"
source_types = {s.source_type for s in sources}
assert "admission_homepage" in source_types, "Missing admission_homepage source"
assert "proposal_pdf" in source_types, "Missing proposal_pdf source"
print("PASS")
