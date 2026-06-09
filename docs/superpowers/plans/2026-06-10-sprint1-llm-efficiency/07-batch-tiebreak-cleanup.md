# Slice 07: Dọn dẹp & regression conflict/e2e

> Part of **Sprint 1 — LLM efficiency**. Spec: `docs/superpowers/specs/2026-06-10-sprint1-llm-efficiency-design.md`
> REQUIRED SUB-SKILL: superpowers:subagent-driven-development / superpowers:executing-plans. Slice này = một commit (tùy chọn). **Phụ thuộc: 06.**

**Goal:** Xác nhận hàm per-conflict cũ không còn call site production, chạy regression rộng cho conflict + e2e.

**Files:**
- Modify (tùy chọn): `services/conflict/resolution_inference_service.py`
- Test: `tests/services/conflict/`, `tests/agents/`, `tests/e2e/test_real_conflict_resolution.py`

---

- [ ] **Step 1: Kiểm tra call site của hàm cũ**

Run: `rg -n "\binterpret_conflict_tiebreak\b" services agents`
Expected: chỉ còn dòng định nghĩa trong `services/conflict/resolution_inference_service.py` (không còn import/call trong `agents/`).
**Khuyến nghị: giữ** hàm cũ + test của nó để giảm bề mặt thay đổi. Chỉ xóa nếu muốn dọn triệt để (kèm xóa các test `test_returns_parsed_data`/`test_degrades_*` cũ trỏ tới nó).

- [ ] **Step 2: Regression conflict + agents**

Run: `python -m pytest tests/services/conflict tests/agents/test_conflict_agent.py -q`
Expected: PASS.

- [ ] **Step 3: Regression e2e (cần Docker DB)**

Đảm bảo DB chạy: `docker compose up -d --wait db`
Run: `python -m pytest tests/e2e/test_real_conflict_resolution.py -q`
Expected: PASS — case decisive resolve không đổi; case indecisive resolve/unresolve đúng như trước.

- [ ] **Step 4: Commit (nếu có dọn dẹp)**

Nếu không sửa gì, bỏ qua. Nếu có:

```bash
git add services/conflict/resolution_inference_service.py tests/services/conflict
git commit -m "chore(conflict): tidy up after batch tiebreak migration"
```

---

## Hoàn tất Sprint 1

Sau slice này: `max_tokens` opt-in theo agent (01–03), fan-out song song (04), batch tiebreak 1-call (05–07). Chạy full suite chốt:

Run: `python -m pytest -q`
Expected: PASS toàn bộ (integration/e2e cần Docker DB).
