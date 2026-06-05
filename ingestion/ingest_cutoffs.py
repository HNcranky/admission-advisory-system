"""CLI: nạp điểm chuẩn lịch sử curated vào cutoff_records (Giai đoạn 2).

    python -m ingestion.ingest_cutoffs --seed                 # seed mặc định
    python -m ingestion.ingest_cutoffs --seed path.json --dry-run
    python -m ingestion.ingest_cutoffs --seed --school hust

Seed phải sạch 100%: BẤT KỲ entry lỗi nào → in toàn bộ lỗi, exit 1, KHÔNG ghi gì
(lỗi resolve ngành nghĩa là cần bổ sung alias programs.json hoặc sửa seed —
không được âm thầm bỏ qua). Exit 2 = validate OK nhưng DB ghi thiếu.
"""
import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from ingestion.config.settings import ADMISSION_YEAR
from ingestion.models.pipeline_models import NormalizedCutoffRecord
from ingestion.normalization.program_mapper import map_program
from ingestion.storage.db_writer import save_cutoff_records
from services.profile.admission_methods import METHOD_CODES

logger = logging.getLogger(__name__)

DEFAULT_SEED = Path(__file__).parent / "cutoff" / "seeds" / "cutoff_2023_2025.json"
MIN_CUTOFF_YEAR = 2020


def load_seed(path: Path) -> list:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_entries(
    entries: list, school_filter: Optional[str] = None,
) -> Tuple[List[NormalizedCutoffRecord], List[str]]:
    """Validate TOÀN BỘ entries; trả (records, errors). errors khác rỗng ⇒ không dùng records."""
    records: List[NormalizedCutoffRecord] = []
    errors: List[str] = []
    for i, e in enumerate(entries):
        if "_notes" in e:
            continue  # phần tử ghi chú curation cuối seed — không phải bản ghi
        school_id = (e.get("school_id") or "").strip()
        if school_filter and school_id != school_filter:
            continue
        label = f"entry[{i}] {school_id or '?'}/{e.get('program_name_raw')}/{e.get('cutoff_year')}"

        if not school_id:
            errors.append(f"{label}: thiếu school_id")
            continue
        method = e.get("admission_method")
        if method not in METHOD_CODES:
            errors.append(f"{label}: admission_method {method!r} không thuộc METHOD_CODES")
            continue
        try:
            score = float(e.get("cutoff_score"))
            scale = float(e.get("score_scale") or 30)
        except (TypeError, ValueError):
            errors.append(f"{label}: cutoff_score/score_scale không phải số ({e.get('cutoff_score')!r})")
            continue
        if not (0 < score <= scale):
            errors.append(f"{label}: cutoff_score {score} ngoài khoảng (0, {scale}]")
            continue
        year = e.get("cutoff_year")
        if not isinstance(year, int) or not (MIN_CUTOFF_YEAR <= year <= ADMISSION_YEAR):
            errors.append(f"{label}: cutoff_year {year!r} ngoài [{MIN_CUTOFF_YEAR}, {ADMISSION_YEAR}]")
            continue
        source_url = (e.get("source_url") or "").strip()
        if not source_url:
            errors.append(f"{label}: thiếu source_url (mỗi con số phải kèm nguồn thật)")
            continue
        program_id, canonical = map_program(
            e.get("program_name_raw"), e.get("program_code_raw"), school_id=school_id,
        )
        if not program_id or program_id == e.get("program_code_raw"):
            errors.append(
                f"{label}: không resolve được ngành {e.get('program_name_raw')!r} "
                "— bổ sung alias vào ingestion/normalization/dictionaries/programs.json"
            )
            continue

        records.append(
            NormalizedCutoffRecord(
                school_id=school_id,
                program_id=program_id,
                program_name_canonical=canonical,
                program_name_raw=e.get("program_name_raw"),
                cutoff_year=year,
                admission_method=method,
                score_scale=scale,
                cutoff_score=score,
                subject_combinations=list(e.get("subject_combinations") or []),
                note=e.get("note"),
                source_url=source_url,
                source_trust_level=int(e.get("source_trust_level") or 3),
            )
        )
    if errors:
        return [], errors
    return records, []


def _main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Nạp điểm chuẩn lịch sử curated vào cutoff_records")
    parser.add_argument("--seed", nargs="?", const=str(DEFAULT_SEED), default=None,
                        help="đường dẫn seed JSON (mặc định: seed commit sẵn)")
    parser.add_argument("--school", default=None, help="chỉ nạp một trường (hust|vnu_uet)")
    parser.add_argument("--dry-run", action="store_true", help="chỉ validate + in, không ghi DB")
    args = parser.parse_args(argv)

    if not args.seed:
        parser.error("cần --seed (đường parser --source-url bổ sung ở plan 5)")

    entries = load_seed(Path(args.seed))
    records, errors = validate_entries(entries, school_filter=args.school)
    if errors:
        print(f"Seed KHÔNG hợp lệ — {len(errors)} lỗi, không ghi gì:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print(f"Validate OK: {len(records)} bản ghi điểm chuẩn.")
    if args.dry_run:
        for r in records:
            print(f"  {r.school_id} {r.cutoff_year} {r.program_id} "
                  f"{r.admission_method} = {r.cutoff_score} ({r.source_url})")
        return 0

    saved = save_cutoff_records(records)
    if saved != len(records):
        print(f"LỖI: chỉ ghi được {saved}/{len(records)} bản ghi — kiểm tra DB/migration 016.")
        return 2
    print(f"Đã upsert {saved} bản ghi vào cutoff_records.")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(_main())
