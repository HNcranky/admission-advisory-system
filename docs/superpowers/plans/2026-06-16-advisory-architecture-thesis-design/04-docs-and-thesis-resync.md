# Plan 04 — Re-sync tài liệu & luận văn (C1 + FACTS/OUTLINE)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Xóa "dead concept" LLM-tiebreaker khỏi tài liệu (C1) và đồng bộ `latex/FACTS.md` + `latex/OUTLINE.md` với cấu trúc code sau cleanup, đảm bảo quy tắc factual-integrity của luận văn.

**Architecture:** Doc-only, zero rủi ro code. **Chạy CUỐI cùng**, sau khi đã chạy các plan code được chọn (01/02/03), để số liệu đo lại chính xác. Mọi số liệu **đo lại bằng lệnh**, không hardcode (robust với bất kỳ tổ hợp plan nào đã chạy).

**Tech Stack:** Markdown. Không cần pytest.

---

### Task 1: C1 — Sửa `CLAUDE.md` (bỏ LLM tiebreaker đã chết)

**Files:** Modify `CLAUDE.md` (dòng ~30)

- [ ] **Step 1: Sửa mô tả `services/conflict/`**

Đổi dòng:
```
  - `services/conflict/` — conflict detection + LLM tiebreaker.
```
thành:
```
  - `services/conflict/` — deterministic conflict detection + resolution (no LLM).
```

- [ ] **Step 2: Xác minh không còn "tiebreaker" trong CLAUDE.md**

Run: `grep -n "tiebreaker" CLAUDE.md`
Expected: **rỗng**.

---

### Task 2: Sửa `latex/OUTLINE.md` (cùng concept đã chết)

**Files:** Modify `latex/OUTLINE.md` (dòng ~85)

- [ ] **Step 1: Sửa mô tả conflict trong dòng đề cương §5.x**

Đổi cụm:
```
`services/conflict/` detection + LLM tiebreaker;
```
thành:
```
`services/conflict/` deterministic detection + resolution;
```

- [ ] **Step 2: Xác minh**

Run: `grep -n "tiebreak" latex/OUTLINE.md`
Expected: **rỗng** (hoặc chỉ còn ở §3.3 nếu nó bàn *lựa chọn thiết kế* — kiểm tra ngữ cảnh, chỉ xóa chỗ mô tả `services/conflict/` đang sai sự thật).

---

### Task 3: Re-sync số liệu `latex/FACTS.md`

**Files:** Modify `latex/FACTS.md`

- [ ] **Step 1: Đo lại số file & LOC (lệnh FACTS.md đã ghi ở dòng 9)**

Run:
```bash
git ls-files '*.py' | wc -l
git ls-files '*.py' | xargs wc -l | tail -1
git ls-files 'agents/*.py' | xargs wc -l | tail -1
git ls-files 'tests/**/*.py' 'tests/*.py' | wc -l
```
Ghi lại các số mới. (Nếu Plan 01 đã chạy: số file `.py` giảm 2; `agents/` LOC giảm ~kích thước shim. Nếu Plan 03 đã chạy: +2 file `keys.py`/`test_keys.py`.)

- [ ] **Step 2: Cập nhật bảng số liệu (dòng ~13–23)**

Trong `latex/FACTS.md`, cập nhật các giá trị đã đổi bằng số đo ở Step 1, ví dụ:
- `| Python files (tracked) | 315 |` → giá trị mới.
- `| agents/ LOC | 271 |` → giá trị mới.
- `| Python LOC (total, incl. tests) | 28,055 |`, `tests/ LOC`, `Production LOC`, `services/ LOC` → giá trị mới nếu đổi.

Chỉ sửa số; giữ nguyên định dạng bảng.

- [ ] **Step 3: Cập nhật số test file (dòng ~64)**

Đếm lại: `git ls-files 'tests/**/test_*.py' 'tests/test_*.py' | wc -l` (hoặc theo cách FACTS.md đang đếm). Cập nhật `Test files: 149` và breakdown `services NN` cho khớp (Plan 01 xóa `test_models_shim.py` → giảm 1; Plan 03 thêm `test_keys.py` → tăng 1; Plan 02 đổi tên — không đổi số).

- [ ] **Step 4: Cập nhật mô tả module `agents/` (dòng ~127–128)**

Nếu Plan 01 đã chạy (đã xóa `agents/models.py`), đổi:
```
7 agent modules in `agents/`: profile, retrieval, conflict, reasoning, policy,
explanation (+ shared `models.py`).
```
thành:
```
6 graph-node modules in `agents/`: profile, retrieval, conflict, reasoning,
policy, explanation. Shared domain models live in `domain/models.py`.
```

- [ ] **Step 5: (Tùy chọn) Thêm con trỏ tới spec kiến trúc**

Nếu FACTS.md/OUTLINE.md có mục tham chiếu thiết kế, thêm 1 dòng trỏ tới
`docs/superpowers/specs/2026-06-16-advisory-architecture-thesis-design.md` (taxonomy 4 lớp + lập luận fixed-graph cho §3.3/§4.1).

---

### Task 4: Commit

- [ ] **Step 1: Xác minh tổng thể không còn concept lỗi thời**

Run: `grep -rn "LLM tiebreaker\|tiebreaker" CLAUDE.md latex/OUTLINE.md latex/FACTS.md`
Expected: rỗng (trừ chỗ §3.3 bàn lựa chọn thiết kế, nếu có — không phải mô tả sai).

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md latex/OUTLINE.md latex/FACTS.md
git commit -m "docs: bỏ LLM-tiebreaker lỗi thời, re-sync FACTS/OUTLINE với cấu trúc mới"
```

---

## Self-Review

- **Spec coverage:** thực thi C1 (§6) + ràng buộc factual-integrity §0 + tiêu chí §9.5 ("CLAUDE.md không còn 'LLM tiebreaker'; FACTS/OUTLINE re-sync"). ✓
- **Placeholder scan:** các số liệu cố ý "đo lại bằng lệnh" (không phải placeholder — là cách đúng để chính xác với tổ hợp plan đã chạy). ✓
- **Thứ tự:** plan này **phải chạy cuối**; nêu rõ ở README. ✓
