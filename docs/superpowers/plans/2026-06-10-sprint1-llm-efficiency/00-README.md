# Sprint 1 — LLM Efficiency (slice index)

> **Spec:** `docs/superpowers/specs/2026-06-10-sprint1-llm-efficiency-design.md`
> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (recommended) hoặc superpowers:executing-plans. **Mỗi slice = một file = một commit.** Steps dùng checkbox `- [ ]`.

Mỗi slice nhỏ, tự chứa (có đủ code + lệnh + test), triển khai độc lập theo thứ tự phụ thuộc bên dưới.

## Danh sách slice

| # | File | Nội dung | Phụ thuộc |
|---|------|----------|-----------|
| 01 | `01-policy-max-tokens.md` | `max_tokens` trên `InferencePolicy` + registry resolve | — |
| 02 | `02-provider-max-output-tokens.md` | `GeminiProvider._call` truyền `max_output_tokens` | 01 |
| 03 | `03-agent-token-budgets.md` | Ngân sách token per agent trong `factory.py` | 01 |
| 04 | `04-parallel-knowledge-fanout.md` | Fan-out kiến thức chạy song song | — |
| 05 | `05-batch-tiebreak-function.md` | Hàm `batch_interpret_conflict_tiebreak` | — |
| 06 | `06-conflict-agent-two-phase.md` | `conflict_agent` 2 pha (1 call thay vì N) | 05 |
| 07 | `07-batch-tiebreak-cleanup.md` | Dọn dẹp + regression conflict/e2e | 06 |

## Thứ tự & song song

- **Nhóm token (01 → 02, 03):** 01 trước; 02 và 03 sau, độc lập nhau.
- **Nhóm fan-out (04):** độc lập hoàn toàn, chạy lúc nào cũng được.
- **Nhóm conflict (05 → 06 → 07):** tuần tự.
- Ba nhóm **độc lập nhau** → có thể giao 3 worker song song.

## Nguyên tắc chung (áp cho mọi slice)

- TDD: viết test fail → chạy thấy fail → implement tối thiểu → chạy thấy pass → commit.
- Python hệ thống (repo không có `.venv`): `python -m pytest ...`.
- Commit message **không** kèm trailer AI; **không** `git push` (CLAUDE.md).
- Bảo toàn hành vi — mỗi slice nêu rõ test chứng minh điều đó.
