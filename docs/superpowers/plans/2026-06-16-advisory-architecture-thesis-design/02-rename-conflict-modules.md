# Plan 02 — Đổi tên module conflict tất định: bỏ hậu tố `_agent` (C2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Đổi tên 3 module **tất định** đang mang tên gây hiểu nhầm "agent" (`comparison_agent.py`, `resolution_agent.py`, `evidence_agent.py`) thành tên trung tính, để code khớp taxonomy luận văn (Lớp 4 = dịch vụ tất định, không phải agent).

**Architecture:** Chỉ đổi **đường dẫn module** (file name); **không** đổi tên hàm public (`compare`, `resolve`, `resolve_cutoff_conflict`, `package_evidence`). `services/conflict/__init__.py` rỗng (không re-export), nên không cần sửa. Importer production duy nhất là `agents/conflict_agent.py` (node graph); còn lại là test.

**Tech Stack:** Python, pytest. **Bảo toàn hành vi tuyệt đối** (chỉ đổi tên file).

**Lệnh test:** `.venv/bin/python -m pytest -q`

**⚠️ Không đụng:** `tests/services/inference/test_gemini_provider.py` — chuỗi `agent="resolution_agent"` ở đó là **agent_name fixture của gateway**, KHÔNG phải module conflict. Các phép thay thế dưới đây dùng đường dẫn đầy đủ `services.conflict.*` nên sẽ không chạm vào nó.

---

### Task 1: Baseline

- [ ] **Step 1: Chạy test, ghi số pass**

Run: `.venv/bin/python -m pytest tests/services/conflict -q`
Expected: PASS (ghi số). Sẽ so lại ở Task 4.

- [ ] **Step 2: Xác nhận importer**

Run: `grep -rn "comparison_agent\|resolution_agent\|evidence_agent" --include=*.py . | grep -v "__pycache__"`
Expected: `agents/conflict_agent.py` (3 dòng), `tests/services/conflict/test_comparison_agent.py`, `test_resolution_agent.py` (2 dòng), `test_evidence_agent.py` (1 dòng), và `test_gemini_provider.py` (2 dòng — KHÔNG đụng).

---

### Task 2: Đổi tên 3 file nguồn + cập nhật mọi import

**Files:**
- Rename: `services/conflict/comparison_agent.py` → `services/conflict/comparison.py`
- Rename: `services/conflict/resolution_agent.py` → `services/conflict/resolution.py`
- Rename: `services/conflict/evidence_agent.py` → `services/conflict/evidence.py`
- Modify (import): `agents/conflict_agent.py`

- [ ] **Step 1: Đổi tên file (giữ lịch sử git)**

```bash
git mv services/conflict/comparison_agent.py services/conflict/comparison.py
git mv services/conflict/resolution_agent.py services/conflict/resolution.py
git mv services/conflict/evidence_agent.py services/conflict/evidence.py
```

- [ ] **Step 2: Cập nhật đường dẫn import toàn repo (an toàn, FQN)**

```bash
grep -rl "services.conflict.comparison_agent\|services.conflict.resolution_agent\|services.conflict.evidence_agent" --include=*.py . \
  | xargs sed -i \
    -e 's/services\.conflict\.comparison_agent/services.conflict.comparison/g' \
    -e 's/services\.conflict\.resolution_agent/services.conflict.resolution/g' \
    -e 's/services\.conflict\.evidence_agent/services.conflict.evidence/g'
```
Sẽ sửa `agents/conflict_agent.py:1,3,4` và 3 file test. KHÔNG chạm `test_gemini_provider.py` (chuỗi bare, không có tiền tố `services.conflict.`).

- [ ] **Step 3: Xác minh không còn đường dẫn cũ**

Run: `grep -rn "conflict\.\(comparison\|resolution\|evidence\)_agent" --include=*.py . | grep -v "__pycache__"`
Expected: **rỗng**.

- [ ] **Step 4: Chạy test conflict**

Run: `.venv/bin/python -m pytest tests/services/conflict tests/agents/test_conflict_agent.py -q`
Expected: PASS (số tương ứng Task 1).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(conflict): đổi tên module tất định, bỏ hậu tố _agent gây hiểu nhầm"
```

---

### Task 3: Đổi tên file test cho nhất quán

**Files:**
- Rename: `tests/services/conflict/test_comparison_agent.py` → `test_comparison.py`
- Rename: `tests/services/conflict/test_resolution_agent.py` → `test_resolution.py`
- Rename: `tests/services/conflict/test_evidence_agent.py` → `test_evidence.py`

- [ ] **Step 1: Đổi tên (import bên trong đã sửa ở Task 2)**

```bash
git mv tests/services/conflict/test_comparison_agent.py tests/services/conflict/test_comparison.py
git mv tests/services/conflict/test_resolution_agent.py tests/services/conflict/test_resolution.py
git mv tests/services/conflict/test_evidence_agent.py tests/services/conflict/test_evidence.py
```

- [ ] **Step 2: Chạy lại toàn bộ test (đảm bảo pytest vẫn thu đủ test sau đổi tên)**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS, tổng số test **không đổi** so với baseline toàn suite (đổi tên file test không làm mất test nào).

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "test(conflict): đổi tên file test khớp module đã đổi tên"
```

---

## Self-Review

- **Spec coverage:** thực thi C2 (§6) + tiêu chí §9.4 (`grep '_agent.py'` trong `services/conflict/` rỗng). ✓
- **Placeholder scan:** không có. ✓
- **Type/đường dẫn consistency:** hàm public không đổi tên; chỉ module path đổi; `__init__.py` rỗng nên không cần sửa. ✓
- **Lưu ý Plan 04:** tên file đổi (không đổi số lượng file/test) — FACTS.md không đổi số đếm, nhưng nếu FACTS liệt kê tên file conflict thì cập nhật.
