# Giai đoạn 2 "Cutoff Store & Conflict mở rộng" — Index kế hoạch triển khai

**Spec:** `docs/superpowers/specs/2026-06-05-phase2-cutoff-store-design.md`
**Edge cases:** EC-14, EC-15, EC-16, EC-18 (+ EC-17 display) trong `docs/edge-case.md`
**Test runner:** `python -m pytest -q` (unit không cần DB; integration/e2e DB cần `docker compose up -d db && python -m db.setup_db`)
**Quy ước:** không `git push`; commit message KHÔNG kèm Co-Authored-By / attribution AI.

> **For agentic workers:** REQUIRED SUB-SKILL: dùng superpowers:subagent-driven-development
> (khuyến nghị) hoặc superpowers:executing-plans để thực thi từng plan theo thứ tự dưới.

## Thứ tự thực thi

| # | Plan | Nội dung | EC | Phụ thuộc |
|---|------|----------|----|-----------|
| 1 | [`...-1-store-seed-loader.md`](2026-06-05-cutoff-1-store-seed-loader.md) — migration 016, models, save_cutoff_records, seed curated + CLI `ingest_cutoffs` | nền dữ liệu | — |
| 2 | [`...-2-retrieval-attach.md`](2026-06-05-cutoff-2-retrieval-attach.md) — `fetch_cutoff_history` + attach vào candidate + integration DB test | nền runtime | Plan 1 |
| 3 | [`...-3-assessment-reasoning-policy.md`](2026-06-05-cutoff-3-assessment-reasoning-policy.md) — `services/cutoff/assessment.py`, reasoning margin-based, 2 policy guardrails | EC-14, EC-15 (+lõi 16/18) | Plan 1 |
| 4 | [`...-4-conflict-explanation-e2e.md`](2026-06-05-cutoff-4-conflict-explanation-e2e.md) — `detect_cutoff_conflicts`, outcome deterministic, explanation + caveat EC-18, fix EC-17, e2e GWT | EC-16, EC-18, EC-17 | Plan 3 (runtime cần Plan 2) |
| 5 | [`...-5-hust-parser.md`](2026-06-05-cutoff-5-hust-parser.md) — parser `tuyensinh247_cutoff_html` (trang điểm chuẩn BKA trên diemthi.tuyensinh247.com, 4 bảng phương thức, trust 3), runner `--source-url` | proof-of-automation | Plan 1 |

**Đợt mở rộng (spec [`2026-06-05-cutoff-tsn247-api-dictionary-design.md`](../specs/2026-06-05-cutoff-tsn247-api-dictionary-design.md)):**

| # | Plan | Nội dung | Phụ thuộc |
|---|------|----------|-----------|
| 6 | [`...-6-bka-dictionary-code-mapping.md`](2026-06-05-cutoff-6-bka-dictionary-code-mapping.md) — programs.json đủ 65 mã BKA (variant tách id riêng) + `map_program` stage match theo mã — **✅ xong 2026-06-05** | Plan 5 |
| 7 | [`...-7-tsn247-api-parser.md`](2026-06-05-cutoff-7-tsn247-api-parser.md) — parser API JSON tsn247, backfill 2022–2024 + re-run HTML 2025 — **✅ xong 2026-06-05** | Plan 6 |
| 8 | [`...-8-reingest-catalog-verify.md`](2026-06-05-cutoff-8-reingest-catalog-verify.md) — re-ingest canonical hust (fix variant Troy đè IT1), rebuild major catalog, verify e2e — **✅ xong 2026-06-05** (kèm fix alias word-boundary + longest-match trong `profile_service`, lộ ra khi smoke) | Plan 6 (khuyến nghị sau 7) |

Plan 2 và Plan 3 độc lập nhau (đều chỉ cần Plan 1). Plan 5 độc lập với 2–4, làm cuối
vì cần network probe. Plan 1 chứa MỘT task thủ công (tra số liệu điểm chuẩn thật) — có
thể làm song song với code các plan sau.

## Định nghĩa hoàn thành (theo AC trong edge-case.md)

- **EC-14:** điểm 26.25, cutoff tham chiếu 26.20 → nhãn sát ngưỡng (`borderline`), band tối đa "match",
  KHÔNG ngôn ngữ khẳng định đỗ; caution nêu năm tham chiếu + chênh lệch.
- **EC-15:** cutoff 24.8/26.7/25.9 (2023–2025), điểm 26.4 → `uncertain`, caution "dao động 24.8–26.7",
  band tối đa "match".
- **EC-16:** hai nguồn ghi 26.2/26.8, điểm 26.5 → conflict flag, hiển thị CẢ HAI giá trị kèm nguồn,
  nhãn bảo thủ, `data_uncertain_fields` chứa `cutoff_score`, KHÔNG LLM pick-winner.
- **EC-18:** mọi câu trả lời dùng cutoff → caveat "Chưa có điểm chuẩn chính thức cho kỳ tuyển sinh
  năm {admission_year}… sử dụng dữ liệu năm {years} làm tham chiếu".
- **EC-17:** quota conflict resolved → `_data_note` liệt kê đủ các giá trị + nguồn, không chỉ winner.

## Sau khi xong cả 5

1. `python -m pytest -q` toàn xanh (DB-less); với Docker DB: integration + e2e xanh.
2. `python -m ingestion.ingest_cutoffs --seed --dry-run` rồi chạy thật; `--seed` idempotent.
3. Smoke thủ công web UI với 4 kịch bản EC-14/15/16/18 (profile thật + data seed).
4. Cập nhật memory `edge-case-conformance`: EC-14/15/16/18 → ĐẠT, EC-17 → ĐẠT.
