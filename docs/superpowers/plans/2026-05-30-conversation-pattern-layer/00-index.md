# Conversation Pattern Layer — Plan Index

Thực thi spec `docs/superpowers/specs/2026-05-30-conversation-pattern-layer-design.md`.

> **Project rule (CLAUDE.md):** KHÔNG bao giờ tự chạy `git commit`/`git push`.
> Các bước "Commit" trong plan = chỉ `git add` (stage) rồi **để user tự commit**.

## Thứ tự thực thi & phụ thuộc

| # | Plan | Nội dung | Phụ thuộc |
|---|------|----------|-----------|
| 01 | `01-router-schema-and-prompt.md` | Mở rộng `IntentResult` (route CONVERSATIONAL, subtype, missing_fields) + cập nhật prompt/few-shots | — |
| 02 | `02-conversational-handler.md` | Module thuần `conversational_handler.py` (templates + response builder) | — |
| 03 | `03-wire-conversational-route.md` | Dispatch CONVERSATIONAL trong `ConversationService` | 01, 02 |
| 04 | `04-slot-aware-clarification.md` | `_handle_clarification` đọc `missing_fields`, hỏi đúng slot | 01 |
| 05 | `05-natural-resume.md` | Thay `_append_return_prompt` bằng offer resume tự nhiên (toàn bộ call site) | 03 |

01 và 02 độc lập, có thể làm song song. 03 cần cả hai. 04 chỉ cần 01. 05 làm
cuối vì refactor resume ở mọi handler (gồm cả handler conversational từ 03).

## Mỗi plan độc lập đạt được gì
- Sau 01: schema + prompt sẵn sàng; test parsing xanh.
- Sau 02: handler conversational test xanh (chưa nối vào service).
- Sau 03: "Xin chào" → greeting thật, không còn câu "nói rõ hơn".
- Sau 04: CLARIFICATION hỏi đúng trường/ngành/tổ hợp thiếu.
- Sau 05: rẽ ngang giữa flow → offer quay lại tự nhiên, không lặp máy móc.

## Lệnh test chung
```powershell
.\.venv\Scripts\python.exe -m pytest tests/services/chat -q
```
