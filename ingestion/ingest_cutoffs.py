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
from ingestion.fetchers.http_fetcher import http_fetch
from ingestion.models.pipeline_models import ExtractedCutoffFact, NormalizedCutoffRecord
from ingestion.normalization.method_mapper import map_method
from ingestion.normalization.program_mapper import map_program
from ingestion.parsers.tuyensinh247_cutoff_parser import Tuyensinh247CutoffParser
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


CUTOFF_PARSERS = {
    Tuyensinh247CutoffParser.parser_profile: Tuyensinh247CutoffParser(),
}

# Thang điểm theo method canonical: THPT thang 30; ĐGTD/XTKH/CCQT trên tuyensinh247 thang 100.
_SCALE_BY_METHOD = {"thpt_score": 30.0}
_DEFAULT_SCALE = 100.0

_SCHOOL_NAMES = {"hust": "Đại học Bách khoa Hà Nội"}


def normalize_cutoff_facts(
    facts: List[ExtractedCutoffFact],
) -> Tuple[List[NormalizedCutoffRecord], List[str]]:
    """Đường parser: per-row skip + báo cáo (khác seed: seed phải atomic-sạch).

    Row không resolve được ngành/method/điểm rác → skip kèm lý do; caller in summary.
    Resolve ngành EXACT-ONLY: trang aggregator liệt kê mọi variant ("KHMT - hợp tác
    ĐH Troy"...), substring/fuzzy sẽ gộp variant vào ngành gốc rồi đè điểm thật
    (key DB không phân biệt tên raw). Coverage điều khiển bằng alias programs.json.
    """
    records: List[NormalizedCutoffRecord] = []
    skipped: List[str] = []
    seen_keys: dict = {}  # (school, year, program, method) → tên raw row đầu (giữ row đầu)
    for f in facts:
        school_id = f.source_reference.school_id
        program_id, canonical = map_program(
            f.program_name, f.program_code, school_id=school_id, exact_only=True,
        )
        if not program_id or program_id == f.program_code:
            skipped.append(f"{f.program_name!r}: không resolve được ngành")
            continue
        method = map_method(f.admission_method_raw, school_id=school_id) if f.admission_method_raw else None
        if method not in METHOD_CODES:
            skipped.append(f"{f.program_name!r}: phương thức {f.admission_method_raw!r} không map được")
            continue
        try:
            score = float((f.cutoff_score_raw or "").replace(",", "."))
        except ValueError:
            skipped.append(f"{f.program_name!r}: điểm {f.cutoff_score_raw!r} không phải số")
            continue
        scale = _SCALE_BY_METHOD.get(method, _DEFAULT_SCALE)
        if not (0 < score <= scale):
            skipped.append(f"{f.program_name!r}: điểm {score} ngoài (0, {scale:g}] của {method}")
            continue
        key = (school_id, f.cutoff_year, program_id, method)
        if key in seen_keys:
            skipped.append(
                f"{f.program_name!r}: trùng ({program_id}, {method}, {f.cutoff_year}) "
                f"với row {seen_keys[key]!r} — giữ row đầu"
            )
            continue
        seen_keys[key] = f.program_name

        records.append(
            NormalizedCutoffRecord(
                school_id=school_id,
                program_id=program_id,
                program_name_canonical=canonical,
                program_name_raw=f.program_name,
                cutoff_year=f.cutoff_year,
                admission_method=method,
                score_scale=scale,
                cutoff_score=score,
                subject_combinations=f.subject_combinations_raw or [],
                note=f.note_raw,
                source_url=f.source_reference.source_url,
                source_trust_level=f.source_reference.trust_level,
                confidence_score=f.confidence_score,
            )
        )
    return records, skipped


def _main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Nạp điểm chuẩn lịch sử curated vào cutoff_records")
    parser.add_argument("--seed", nargs="?", const=str(DEFAULT_SEED), default=None,
                        help="đường dẫn seed JSON (mặc định: seed commit sẵn)")
    parser.add_argument("--school", default=None, help="chỉ nạp một trường (hust|vnu_uet)")
    parser.add_argument("--dry-run", action="store_true", help="chỉ validate + in, không ghi DB")
    parser.add_argument("--source-url", default=None, help="URL trang điểm chuẩn (đường parser)")
    parser.add_argument("--parser", default="tuyensinh247_cutoff_html", choices=sorted(CUTOFF_PARSERS),
                        help="parser profile cho --source-url")
    parser.add_argument("--year", type=int, default=None,
                        help="filter cutoff_year (đường parser; mặc định lấy mọi năm parser đọc được từ heading)")
    parser.add_argument("--trust", type=int, default=3,
                        help="trust level nguồn (đường parser; mặc định 3 — aggregator)")
    args = parser.parse_args(argv)

    if args.source_url:
        fetch = http_fetch(args.source_url)
        if not fetch or fetch.http_status >= 400:
            print(f"LỖI fetch {args.source_url}: HTTP {getattr(fetch, 'http_status', '?')}")
            return 1
        cutoff_parser = CUTOFF_PARSERS[args.parser]
        facts = cutoff_parser.parse(
            fetch.raw_content, args.source_url, cutoff_year=args.year,
            school_id=args.school or "hust",
            school_name=_SCHOOL_NAMES.get(args.school or "hust", args.school or "hust"),
            trust_level=args.trust,
        )
        records, skipped = normalize_cutoff_facts(facts)
        for reason in skipped:
            print(f"  SKIP {reason}")
        if not records:
            print("Không có bản ghi hợp lệ nào từ nguồn — kiểm tra parser/dictionary.")
            return 1
        if args.dry_run:
            for r in records:
                print(f"  {r.school_id} {r.cutoff_year} {r.admission_method} {r.program_id} = {r.cutoff_score}")
            return 0
        saved = save_cutoff_records(records)
        print(f"Đã upsert {saved}/{len(records)} bản ghi (skip {len(skipped)} row).")
        return 0 if saved == len(records) else 2

    if not args.seed:
        parser.error("cần --seed hoặc --source-url")

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
