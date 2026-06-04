# Giai đoạn 1 "Reasoning Integrity" — Index kế hoạch triển khai

**Spec:** `docs/superpowers/specs/2026-06-04-phase1-reasoning-integrity-design.md`
**Edge cases:** EC-04, EC-12, EC-13, EC-22, EC-24 trong `docs/edge-case.md`
**Test runner:** `python -m pytest -q` (system Python 3.12 — repo KHÔNG có venv; unit/conversation test không cần DB)
**Quy ước:** không `git push`; commit message KHÔNG kèm Co-Authored-By / attribution AI.

## Thứ tự thực thi (bắt buộc)

| # | Plan | EC | Phụ thuộc |
|---|------|----|-----------|
| 1 | [`...-1-method-foundation.md`](2026-06-04-reasoning-integrity-1-method-foundation.md) — module admission_methods, slot mới, parse_score fix, models, extractor | EC-13 (thu thập) | — |
| 2 | [`...-2-score-validation.md`](2026-06-04-reasoning-integrity-2-score-validation.md) — validate_profile_delta R1/R2 + _handle_rejection | EC-04 | Plan 1 |
| 3 | [`...-3-reasoning-eligibility.md`](2026-06-04-reasoning-integrity-3-reasoning-eligibility.md) — 3 ngả reasoning + policy flags | EC-12, EC-13 | Plan 1 |
| 4 | [`...-4-reset-intent.md`](2026-06-04-reasoning-integrity-4-reset-intent.md) — reset hai lớp + RESET_PROFILE route | EC-22 | Plan 2 (dùng validate trong handler) |
| 5 | [`...-5-explanation-transparency.md`](2026-06-04-reasoning-integrity-5-explanation-transparency.md) — section Không đủ điều kiện + no-match minh bạch | EC-12 (hiển thị), EC-24 | Plan 1, 3 |

Ghi chú thứ tự: Plan 1 → 2 nên đi liền nhau (Plan 1 nới `parse_score` lên 150; trần theo phương thức chỉ có hiệu lực khi Plan 2 xong). Plan 3 và Plan 4 độc lập nhau (đều sau dependency của mình); Plan 5 cuối cùng.

## Định nghĩa hoàn thành (theo AC trong edge-case.md)

- **EC-04:** "Em được 35 điểm theo thang 30" (method=thpt_score) → điểm KHÔNG lưu, trả lời yêu cầu kiểm tra/làm rõ phương thức.
- **EC-12:** điểm 28 D01, chương trình chỉ nhận A00/A01 → không nằm trong đề xuất; section "Không đủ điều kiện xét tuyển" nêu lý do tổ hợp.
- **EC-13:** "Em được 27 điểm" → hệ thống hỏi "phương thức nào"; pipeline không chấm score-fit khi method thiếu.
- **EC-22:** "Xoá thông tin cũ đi..." → hồ sơ trắng, hỏi lại từ slot đầu; retrieval sau đó không dùng hồ sơ cũ; delta cùng lượt áp lên hồ sơ mới.
- **EC-24:** 0 kết quả → liệt kê đúng tiêu chí đang áp, gợi ý nới minh bạch, không bịa, không tự nới.

## Sau khi xong cả 5

1. `python -m pytest -q` toàn xanh.
2. Smoke thủ công qua web UI (`python -m uvicorn web.app:app --reload`) với 5 kịch bản trên.
3. Cập nhật memory đánh giá edge-case (kỳ vọng: EC-04/12/13/22 chuyển ĐẠT, EC-24 chuyển ĐẠT phần message; EC-14/15/16/18 vẫn chờ Giai đoạn 2 — cutoff store).
