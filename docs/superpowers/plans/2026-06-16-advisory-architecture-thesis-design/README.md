# Kế hoạch triển khai — Kiến trúc đích cho luận văn

Nhóm plan cho spec `docs/superpowers/specs/2026-06-16-advisory-architecture-thesis-design.md`.
Mục tiêu chung: **gỡ nợ khái niệm + xóa mâu thuẫn code↔thesis**, **bảo toàn 100% hành vi**.

Spec quyết định KHÔNG thêm agent runtime. Phần "implementation" chỉ gồm 4 cleanup an
toàn (C1–C4) + re-sync tài liệu/luận văn. Mỗi plan **tự chứa** (chạy/hoãn độc lập), có
lưới an toàn = bộ test hiện có **xanh y nguyên**.

## Danh sách plan

| Plan | Cleanup | Rủi ro | Phụ thuộc | Có thể hoãn? |
|---|---|---|---|---|
| [01 — Sửa đảo tầng models](01-layering-fix-domain-models.md) | C3 | Thấp (cơ học) | — | Không nên (nền cho thesis "no inversion") |
| [02 — Đổi tên module conflict](02-rename-conflict-modules.md) | C2 | Thấp | nên sau 01 | Có |
| [03 — Gom conflict-key](03-conflict-key-consolidation.md) | C4 | **Trung bình** | nên sau 01,02 | **Có — item dễ hoãn nhất** |
| [04 — Re-sync tài liệu & luận văn](04-docs-and-thesis-resync.md) | C1 + FACTS/OUTLINE | Zero (doc) | **chạy CUỐI** (sau plan đã chọn) | — |

## Thứ tự khuyến nghị

`01 → 02 → 03 → 04`. Lý do: 01 chuẩn hóa import `domain.models` trước; 02 đổi tên file
conflict; 03 đụng logic conflict-key; 04 đo lại số liệu file/LOC/test **sau cùng** để
FACTS.md chính xác. Nếu gần mốc nộp luận văn: chạy **01 + 02 + 04**, hoãn **03**.

## Lưới an toàn chung (mọi plan)

- Lệnh test (Ubuntu): `.venv/bin/python -m pytest -q` (chỉnh theo venv của bạn; xem
  `CLAUDE.md`). Test chạy trên DB `admission_test` tự tạo, không đụng `admission`.
- Bất biến nghiệm thu: **số test pass trước = sau**; 6 endpoint HTTP + shape phản hồi
  không đổi.
- Theo `CLAUDE.md`: **không `git push`**, commit message **không** trailer
  `Co-Authored-By`/attribution AI.
