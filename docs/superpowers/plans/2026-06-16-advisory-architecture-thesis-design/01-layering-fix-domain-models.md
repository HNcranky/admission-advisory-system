# Plan 01 — Sửa đảo tầng: `agents.models` → `domain.models` (C3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Loại bỏ đảo tầng `services/* → agents/*`: chuyển mọi import từ shim `agents.models` sang nguồn chuẩn `domain.models`, rồi xóa shim.

**Architecture:** `agents/models.py` hiện chỉ là shim re-export từ `domain/models.py` (đã có sẵn, chứa các Pydantic model dùng chung). Mọi symbol y hệt nhau, nên đổi import là thay thế cơ học bảo toàn hành vi. Sau khi không còn ai import `agents.models`, xóa shim + test canh shim.

**Tech Stack:** Python, Pydantic v2, pytest. DB test `admission_test` (tự tạo, isolated).

**Lệnh test (chỉnh theo venv của bạn):** `.venv/bin/python -m pytest -q`

---

### Task 1: Ghi nhận baseline (lưới an toàn)

**Files:** không sửa — chỉ đo.

- [ ] **Step 1: Chạy toàn bộ test, ghi số pass**

Run: `.venv/bin/python -m pytest -q`
Expected: suite hiện tại PASS (ghi lại con số, ví dụ "NNN passed, 1 skipped"). Đây là mốc bất biến — Task 4 phải khớp số này.

- [ ] **Step 2: Liệt kê toàn bộ importer của `agents.models`**

Run: `grep -rn "agents\.models" --include=*.py . | grep -v "__pycache__"`
Expected: ~13 file production + ~20 dòng test + `agents/models.py` (chính shim) + `domain/models.py:43` (comment). Ghi nhớ để Step verify Task 4 về 0 (ngoài chỗ đã xóa/sửa).

---

### Task 2: Di chuyển import sang `domain.models`

**Files:** Modify (bulk): mọi `*.py` có `from agents.models import` TRỪ `agents/models.py`.

- [ ] **Step 1: Bulk-replace import (cơ học, symbol y hệt)**

Run:
```bash
grep -rl "from agents.models import" --include=*.py . \
  | grep -v "agents/models.py" \
  | xargs sed -i 's/from agents\.models import/from domain.models import/g'
```
Lệnh này thay cả dòng đơn (`from agents.models import X`) lẫn dòng mở ngoặc nhiều dòng (`from agents.models import (`). Không đụng `agents/models.py` (shim).

- [ ] **Step 2: Xác minh không còn `from agents.models` (trừ shim)**

Run: `grep -rn "from agents.models" --include=*.py . | grep -v "__pycache__"`
Expected: chỉ còn dòng trong `agents/models.py` (shim, sẽ xóa ở Task 3). Không còn ở `services/`, `web/`, `ingestion/`, `tests/`.

- [ ] **Step 3: Chạy test để chắc hành vi không đổi**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS, **đúng số pass như Task 1 Step 1** (test_models_shim.py vẫn còn ở bước này nên vẫn pass).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(models): import domain.models thay cho shim agents.models"
```

---

### Task 3: Xóa shim + test canh shim, sửa comment lệch

**Files:**
- Delete: `agents/models.py`
- Delete: `tests/domain/test_models_shim.py` (test canh shim — vô nghĩa khi shim biến mất)
- Modify: `domain/models.py:43` (comment nói model "Đặt ở agents.models" — sai sau khi shim đi)

- [ ] **Step 1: Còn ai dùng `import agents.models` (dạng module) không?**

Run: `grep -rn "import agents.models\|agents\.models" --include=*.py . | grep -v "__pycache__" | grep -v "agents/models.py" | grep -v "domain/models.py"`
Expected: chỉ còn `tests/domain/test_models_shim.py` (dùng `import agents.models as shim`). Xác nhận trước khi xóa shim.

- [ ] **Step 2: Xóa shim và test canh shim**

```bash
git rm agents/models.py tests/domain/test_models_shim.py
```

- [ ] **Step 3: Sửa comment lệch trong `domain/models.py`**

Trong `domain/models.py` dòng ~43, đổi:
```
    Đặt ở agents.models (không phải services/cutoff) để tránh vòng import:
```
thành:
```
    Đặt ở domain.models (không phải services/cutoff) để tránh vòng import:
```
(Chỉ đổi `agents.models` → `domain.models` trong câu comment; giữ nguyên phần còn lại.)

- [ ] **Step 4: Xác minh sạch hoàn toàn**

Run: `grep -rn "agents.models" --include=*.py . | grep -v "__pycache__"`
Expected: **rỗng** (không còn bất kỳ tham chiếu `agents.models` nào).

- [ ] **Step 5: Chạy test toàn bộ**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. Số pass = (Task 1 Step 1) **trừ số test trong `test_models_shim.py`** đã xóa (ghi rõ chênh lệch để Plan 04 cập nhật FACTS.md). Không có FAIL/ERROR mới.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(models): xóa shim agents/models.py, dùng domain.models trực tiếp"
```

---

## Self-Review

- **Spec coverage:** thực thi C3 (§6 spec) + tiêu chí §9.4 ("không còn import agents.models ngoài shim đã xóa"). ✓
- **Placeholder scan:** không có; mọi lệnh/edit cụ thể. ✓
- **Lưu ý cho Plan 04:** ghi lại (a) số file `.py` giảm 2 (`agents/models.py`, `test_models_shim.py`); (b) `agents/` LOC giảm; (c) số test file giảm 1 (thuộc nhóm `services`/`domain`). FACTS.md sẽ re-sync ở Plan 04.
