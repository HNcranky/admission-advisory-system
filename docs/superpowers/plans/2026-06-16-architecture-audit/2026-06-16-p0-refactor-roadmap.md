# P0 Refactor Roadmap — Dọn an toàn (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (khuyến nghị) hoặc superpowers:executing-plans để thực thi từng task. Các bước dùng checkbox (`- [ ]`) để theo dõi.

**Goal:** Thực thi nhóm P0 của audit `docs/superpowers/specs/2026-06-16-architecture-audit.md` — xóa dead code, dọn lint, gỡ dependency thừa — bằng các PR nhỏ, mỗi PR giữ app chạy được, **ưu tiên xóa hơn viết lại**.

**Architecture:** Toàn bộ P0 là *thay đổi không đổi hành vi runtime*: mọi symbol bị xóa đã được xác minh `0 ref` ngoài định nghĩa (bằng `git grep`). Không đụng public API đang dùng, không đụng schema DB, không đụng data path đang chạy. Các quyết định "lửng lơ" (data path `raw_documents/extracted_facts`, ABC provider thật) được **để lại cho P2** — P0 chỉ gỡ phần chết.

**Tech Stack:** Python 3.12, psycopg2, FastAPI, pytest. Lệnh test chuẩn (Linux): `python -m pytest -q`.

**Quy ước test cho plan deletion-heavy này:** TDD cổ điển (viết test đỏ trước) không áp dụng cho thao tác *xóa*. "Test đỏ" được thay bằng **bằng chứng `git grep` = 0 ref** (chứng minh symbol chết) + **full suite xanh sau khi xóa** + **smoke import**. Định dạng mỗi PR theo yêu cầu: Title / Goal / Files to modify / Files to delete / Migration strategy / Test plan / Rollback strategy.

**Thứ tự (an toàn → rủi ro hơn):** PR1 → PR2 → PR3 → PR4 → PR5 → PR6 → PR7. Mỗi PR độc lập, merge riêng, app luôn xanh giữa các PR.

> ⚠️ CLAUDE.md: **không bao giờ `git push`**, **không thêm trailer `Co-Authored-By`/AI attribution** vào commit message.

---

## PR1 — Xóa các hàm/class app-logic chết (0 ref)

**Title:** `refactor(dead-code): remove unreferenced app-logic symbols`

**Goal:** Gỡ 5 symbol thuần logic, `0 ref` toàn repo, không liên quan DB/data path — giảm bề mặt bảo trì với rủi ro thấp nhất.

**Files to modify:**
- `services/reasoning_service.py` — xóa `index_candidates_by_id` (def tại `:251`)
- `services/retrieval_service.py` — xóa `detect_conflicts` (def tại `:221`; logic thật nằm ở `services/conflict/`)
- `services/chat/models.py` — xóa `class AdvisoryRunRecord` (def tại `:64`)
- `ingestion/parsers/hust_program_parser.py` — xóa `parse_hust_programs` ("Legacy entry point", `:719`)
- `ingestion/pipeline/ingestion_pipeline.py` — xóa `run_ingestion` ("Legacy entry point", `:263`)

**Files to delete:** (none)

**Migration strategy:** Không có caller → xóa thẳng định nghĩa hàm/class. Sau khi xóa, kiểm tra import "mồ côi" mới phát sinh ở đầu mỗi file (vd: type chỉ dùng bởi hàm vừa xóa) và gỡ nếu có. Không tạo shim (không ai import nên không cần giữ tương thích).

**Test plan:**
- [ ] **Step 1 — Chứng minh chết.** Chạy, kỳ vọng mỗi symbol ra đúng 1 dòng (chính `def`/`class`):
  ```bash
  for s in index_candidates_by_id detect_conflicts AdvisoryRunRecord parse_hust_programs run_ingestion; do
    echo -n "$s : "; git grep -n "$s" -- '*.py' | grep -v '\.venv' | wc -l
  done
  ```
  Kỳ vọng: tất cả `= 1`. Cũng grep `*.md`/`scripts/` để chắc không có ref docs/probe:
  ```bash
  git grep -n "parse_hust_programs\|run_ingestion" -- '*.md' 'scripts/*'
  ```
  Kỳ vọng: không có dòng nào (hoặc chỉ docs mô tả — không phải lời gọi).
- [ ] **Step 2 — Xóa 5 symbol** ở 5 file trên; gỡ import mồ côi nếu phát sinh.
- [ ] **Step 3 — Smoke import** (bắt lỗi cú pháp/import ngay):
  ```bash
  python -c "import services.reasoning_service, services.retrieval_service, services.chat.models, ingestion.parsers.hust_program_parser, ingestion.pipeline.ingestion_pipeline"
  ```
  Kỳ vọng: thoát 0, không traceback.
- [ ] **Step 4 — Full suite.** `python -m pytest -q` → kỳ vọng PASS (không cần Docker cho unit; integration skip nếu thiếu DB).
- [ ] **Step 5 — Commit.**
  ```bash
  git add services/reasoning_service.py services/retrieval_service.py services/chat/models.py ingestion/parsers/hust_program_parser.py ingestion/pipeline/ingestion_pipeline.py
  git commit -m "refactor(dead-code): remove unreferenced app-logic symbols"
  ```

**Rollback strategy:** `git revert <sha>` — PR thuần xóa, revert khôi phục nguyên trạng, không side effect (DB/API không đổi).

---

## PR2 — Dọn dòng whitespace divider chết

**Title:** `style: remove dead whitespace-only divider lines`

**Goal:** Xóa các dòng chỉ-toàn-khoảng-trắng (tàn dư divider `#...` cũ bị xóa mất `#`), làm sạch lint. Thuần format, không đụng logic.

**Files to modify:**
- `ingestion/storage/db_writer.py` (các dòng whitespace-only: 1, 29, 81, 132, 224)
- `ingestion/parsers/hust_program_parser.py` (1, 34, 163, 188, …)
- `ingestion/pipeline/ingestion_pipeline.py` (1, 74, 83, 88, 94)

**Files to delete:** (none)

**Migration strategy:** Thay vì sửa từng số dòng (dễ lệch), dùng phép biến đổi xác định: **chuyển các dòng chỉ chứa khoảng trắng thành dòng trống** trong đúng 3 file. Không gộp dòng, không xóa dòng trống hợp lệ → giữ nguyên cấu trúc, diff tối thiểu.
```bash
sed -i 's/^[[:space:]]\+$//' \
  ingestion/storage/db_writer.py \
  ingestion/parsers/hust_program_parser.py \
  ingestion/pipeline/ingestion_pipeline.py
```

**Test plan:**
- [ ] **Step 1 — Áp dụng `sed`** ở trên.
- [ ] **Step 2 — Xác nhận chỉ đổi whitespace.** `git diff -w --stat` → kỳ vọng **rỗng** (diff khi bỏ qua whitespace = không có thay đổi logic).
- [ ] **Step 3 — Smoke import** 3 module:
  ```bash
  python -c "import ingestion.storage.db_writer, ingestion.parsers.hust_program_parser, ingestion.pipeline.ingestion_pipeline"
  ```
- [ ] **Step 4 — Full suite.** `python -m pytest -q` → PASS.
- [ ] **Step 5 — Commit.**
  ```bash
  git add ingestion/storage/db_writer.py ingestion/parsers/hust_program_parser.py ingestion/pipeline/ingestion_pipeline.py
  git commit -m "style: remove dead whitespace-only divider lines"
  ```

**Rollback strategy:** `git revert <sha>`. Vì `git diff -w` rỗng, rollback hoàn toàn vô hại.

---

## PR3 — Đưa import của `intent_router` lên đầu file

**Title:** `style: hoist mid-file imports in intent_router to module top`

**Goal:** Gom 4 import nằm giữa file (`services/chat/intent_router.py:31-34`) lên đầu module theo PEP8. Nhỏ nhưng tách riêng vì có **rủi ro circular-import** (import giữa file đôi khi là cách né vòng lặp).

**Files to modify:**
- `services/chat/intent_router.py` — di chuyển 4 dòng sau lên cụm import đầu file (sau các import stdlib/pydantic hiện có):
  ```python
  from services import build_default_gateway
  from services.chat.models import ChatProfileState
  from services.inference.models import InferenceRequest
  from services.profile_service import normalize_text
  ```

**Files to delete:** (none)

**Migration strategy:** Cắt 4 dòng tại vị trí cũ (sau hàm/hằng `_TOPIC_SYNONYMS`), dán vào cuối khối import đầu file. Không đổi nội dung import. **Nếu** smoke import báo `ImportError` vòng lặp → giữ nguyên vị trí cũ và **chỉ thêm comment `# noqa: E402 — mid-file import tránh circular`**, ghi chú lại để P2 xử lý gốc (move domain models). Đây là fallback an toàn, vẫn đóng được PR.

**Test plan:**
- [ ] **Step 1 — Xác minh không vòng lặp tĩnh** (services/__init__ chỉ export `build_default_gateway` từ `factory`, không import `chat` — nhưng vẫn test runtime):
  ```bash
  python -c "import services.chat.intent_router as m; print('ok')"
  ```
  Kỳ vọng: in `ok`, không traceback. **Nếu lỗi → dùng fallback `# noqa` ở Migration.**
- [ ] **Step 2 — Hoist 4 import** lên đầu (hoặc fallback).
- [ ] **Step 3 — Smoke import lại** (Step 1) → `ok`.
- [ ] **Step 4 — Test trực tiếp router + web boot:**
  ```bash
  python -m pytest -q tests/services/chat/ -k intent
  python -c "import web.app; print('app ok')"
  ```
  Kỳ vọng: PASS + `app ok`.
- [ ] **Step 5 — Full suite.** `python -m pytest -q` → PASS.
- [ ] **Step 6 — Commit.**
  ```bash
  git add services/chat/intent_router.py
  git commit -m "style: hoist mid-file imports in intent_router to module top"
  ```

**Rollback strategy:** `git revert <sha>`. Thay đổi cục bộ 1 file; revert đưa import về vị trí cũ.

---

## PR4 — Xóa các hàm ghi storage chết trong `db_writer` (gộp luôn `psycopg2_Binary`)

**Title:** `refactor(storage): remove dead write functions in db_writer`

**Goal:** Gỡ 4 hàm `0 ref` ghi vào `raw_documents`/`extracted_facts` mà **pipeline thật không bao giờ gọi** (chỉ `save_canonical_records`/`save_cutoff_records` được dùng). **Thay thế task "đổi tên `psycopg2_Binary`→`_to_db_binary`" của audit bằng xóa luôn** — vì nó chỉ được gọi bởi `save_raw_document` (cũng chết), đúng tinh thần *xóa hơn viết lại*.

**Files to modify:**
- `ingestion/storage/db_writer.py`:
  - Xóa `save_raw_document` (`:31`)
  - Xóa `psycopg2_Binary` (`:75`) — chỉ caller là `save_raw_document:59`, mất theo
  - Xóa `save_extracted_facts` (`:83`)
  - Xóa `load_and_save_from_json` (`:226`)
  - **Prune import mồ côi sau khi xóa:** bỏ `FetchResult, DocumentType, ParsedContent` khỏi khối `from ingestion.models.pipeline_models import (...)` (chỉ `save_raw_document` dùng). **Giữ** `json`, `Optional`, `List`, `ExtractedAdmissionFact`, `NormalizedAdmissionRecord`, `NormalizedCutoffRecord` (còn dùng bởi 2 hàm sống).

**Files to delete:** (none — file `db_writer.py` vẫn còn 2 hàm sống)

**Migration strategy:** Xóa thân 4 hàm. Tuyệt đối **không** đụng bảng `raw_documents`/`extracted_facts` và **không** đụng `services/conflict/evidence_agent.py` (LEFT JOIN 2 bảng đó) — quyết định data path để lại P2 (§1 audit, confidence TB). Vì 4 hàm hiện đã không bao giờ chạy, runtime không đổi. Sau prune import, chạy linter để chắc không còn unused.

**Test plan:**
- [ ] **Step 1 — Chứng minh chết:**
  ```bash
  for s in save_raw_document save_extracted_facts load_and_save_from_json psycopg2_Binary; do
    echo -n "$s : "; git grep -n "$s" -- '*.py' | grep -v '\.venv' | wc -l
  done
  ```
  Kỳ vọng: `save_raw_document=1`, `save_extracted_facts=1`, `load_and_save_from_json=1`, `psycopg2_Binary=2` (def + 1 caller nội bộ sắp xóa). Xác nhận `save_canonical_records`/`save_cutoff_records` **không** gọi 4 hàm này.
- [ ] **Step 2 — Xóa 4 hàm + prune 3 import** (`FetchResult, DocumentType, ParsedContent`).
- [ ] **Step 3 — Smoke import + kiểm 2 hàm sống còn nguyên:**
  ```bash
  python -c "from ingestion.storage.db_writer import save_canonical_records, save_cutoff_records; print('ok')"
  ```
  Kỳ vọng: `ok` (chứng minh không vô tình xóa nhầm + import prune đúng).
- [ ] **Step 4 — Test storage/integration** (cần Docker DB nếu có; nếu không, integration tự skip):
  ```bash
  docker compose up -d --wait db   # nếu muốn chạy integration
  python -m pytest -q tests -k "writer or canonical or cutoff or storage"
  ```
- [ ] **Step 5 — Full suite.** `python -m pytest -q` → PASS.
- [ ] **Step 6 — Commit.**
  ```bash
  git add ingestion/storage/db_writer.py
  git commit -m "refactor(storage): remove dead write functions in db_writer"
  ```

**Rollback strategy:** `git revert <sha>`. Không có migration DB, không đổi schema → revert đưa lại 4 hàm chết, an toàn tuyệt đối.

---

## PR5 — Xóa 2 file chết hoàn toàn

**Title:** `refactor(dead-code): delete unused admission_schema and provider base`

**Goal:** Xóa 2 module `0 importer`: domain schema cũ đã bị thay bởi `pipeline_models.py`, và ABC provider không ai kế thừa.

**Files to modify:** (none — không có importer cần sửa)

**Files to delete:**
- `ingestion/models/admission_schema.py` (`AdmissionMethod`/`ProgramAdmission`/`AdmissionDocument` — đã được mô hình hóa đầy đủ hơn bởi `ExtractedAdmissionFact`/`NormalizedAdmissionRecord`)
- `services/inference/providers/base.py` (`BaseInferenceProvider(ABC)` — đã xác minh `GeminiProvider` **không** kế thừa nó; gateway hardcode `"gemini"`)

**Migration strategy:** Xóa 2 file. Việc "làm ABC thật hay inline" (§4 mục 2) là quyết định kiến trúc thuộc **P2** — P0 chỉ gỡ ABC chết. Không tạo shim (0 importer).

**Test plan:**
- [ ] **Step 1 — Chứng minh 0 importer:**
  ```bash
  git grep -ln "admission_schema\|AdmissionMethod\|ProgramAdmission\|AdmissionDocument" -- '*.py' | grep -v admission_schema.py
  git grep -ln "providers.base\|BaseInferenceProvider" -- '*.py' | grep -v providers/base.py
  ```
  Kỳ vọng: **cả hai lệnh không in gì.**
- [ ] **Step 2 — Xóa 2 file:**
  ```bash
  git rm ingestion/models/admission_schema.py services/inference/providers/base.py
  ```
- [ ] **Step 3 — Smoke import package liên quan:**
  ```bash
  python -c "import ingestion.models.pipeline_models, services.inference.providers.gemini_provider; print('ok')"
  ```
  Kỳ vọng: `ok`.
- [ ] **Step 4 — Full suite.** `python -m pytest -q` → PASS.
- [ ] **Step 5 — Commit.**
  ```bash
  git commit -m "refactor(dead-code): delete unused admission_schema and provider base"
  ```

**Rollback strategy:** `git revert <sha>` khôi phục cả 2 file. Vì 0 importer, không có gì phụ thuộc.

---

## PR6 — Gỡ 5 dependency thừa khỏi `requirements.txt`

**Title:** `build(deps): drop unused langchain/httpx/tenacity/certifi/python-dateutil`

**Goal:** Giảm bề mặt build/CVE bằng cách bỏ 5 package `0 hit` trong code. Đặt **gần cuối** vì thay đổi dependency-resolution có blast radius rộng nhất (build/CI) dù risk logic thấp.

**Files to modify:**
- `requirements.txt` — xóa 5 dòng:
  - `langchain==1.2.17` (chỉ `langgraph` được dùng; `langchain` là package riêng, chết)
  - `httpx==0.28.1` (mọi HTTP qua `requests`; `httpx` chỉ là transitive của Starlette `TestClient`)
  - `tenacity==9.1.4` (retry tự viết tay ở `http_fetcher`/`key_pool`)
  - `certifi==2026.4.22` (kéo transitive bởi `requests`)
  - `python-dateutil==2.9.0.post0` (code dùng `datetime` stdlib)

**Files to delete:** (none)

**Migration strategy:** Xóa 5 pin trực tiếp. `httpx`/`certifi` vẫn được cài lại **transitively** (TestClient cần httpx, requests cần certifi) → không pin trực tiếp nữa nhưng vẫn có mặt khi cần. Tạo venv sạch để chứng minh không vỡ resolution.

**Test plan:**
- [ ] **Step 1 — Chứng minh 0 hit code:**
  ```bash
  git grep -nE "import (langchain|httpx|tenacity|certifi|dateutil)|from (langchain|httpx|tenacity|certifi|dateutil)" -- '*.py' | grep -v '\.venv'
  ```
  Kỳ vọng: **không in gì.** (Lưu ý: `langgraph` khác `langchain` — không match.)
- [ ] **Step 2 — Xóa 5 dòng** khỏi `requirements.txt`.
- [ ] **Step 3 — Cài lại sạch trong venv tạm** (không phá `.venv` chính):
  ```bash
  python -m venv /tmp/p0venv && /tmp/p0venv/bin/pip install -q -r requirements.txt
  ```
  Kỳ vọng: cài thành công, không lỗi resolution.
- [ ] **Step 4 — Smoke + full suite trong venv tạm:**
  ```bash
  /tmp/p0venv/bin/python -c "import web.app, langgraph; print('ok')"
  /tmp/p0venv/bin/python -m pytest -q
  ```
  Kỳ vọng: `ok` + suite PASS (đặc biệt test web dùng `TestClient` → chứng minh httpx transitive vẫn còn).
- [ ] **Step 5 — Commit.**
  ```bash
  git add requirements.txt
  git commit -m "build(deps): drop unused langchain/httpx/tenacity/certifi/python-dateutil"
  ```

**Rollback strategy:** `git revert <sha>` đưa lại 5 pin. Nếu CI/môi trường nào đó vỡ vì transitive bị đổi version → revert ngay là đủ; không có state nào khác bị ảnh hưởng.

---

## PR7 — (Cần phê duyệt) Xóa module `profile_state_service`

**Title:** `refactor(dead-code): remove deprecated profile_state_service`

**Goal:** Gỡ module chỉ được import bởi **chính test của nó** (`parse_pending_slot_answer` 0 ref thật; `merge_profile_state` docstring ghi "DEPRECATED khỏi conversation flow").

> ⚠️ **GATE — cần phê duyệt rõ ràng trước khi làm.** Rule của task: *"Preserve all public APIs unless explicitly approved."* Đây là **xóa nguyên 1 service module** → coi là public API. **Không thực thi PR7 nếu chưa được người dùng đồng ý.** Nếu chỉ được duyệt một phần, làm biến thể tối thiểu: chỉ xóa `parse_pending_slot_answer` (0 ref tuyệt đối), giữ phần còn lại.

**Files to modify:** (none nếu xóa cả module; nếu biến thể tối thiểu → sửa `services/chat/profile_state_service.py` bỏ `parse_pending_slot_answer` + test tương ứng)

**Files to delete (bản đầy đủ, sau khi được duyệt):**
- `services/chat/profile_state_service.py`
- `tests/services/chat/test_profile_state_service.py`

**Migration strategy:** Đã xác minh importer duy nhất là file test của chính nó (`git grep -ln profile_state_service` → chỉ ra file test). Xóa cặp module+test cùng nhau. Không shim.

**Test plan:**
- [ ] **Step 0 — GATE.** Hỏi & nhận phê duyệt. Nếu không → dừng PR7 (hoặc chuyển biến thể tối thiểu).
- [ ] **Step 1 — Chứng minh importer = chỉ test của nó:**
  ```bash
  git grep -ln "profile_state_service\|parse_pending_slot_answer\|merge_profile_state" -- '*.py' | grep -v test_profile_state_service
  ```
  Kỳ vọng: **không in gì** (mọi tham chiếu nằm trong module + test của nó).
- [ ] **Step 2 — Xóa cặp file:**
  ```bash
  git rm services/chat/profile_state_service.py tests/services/chat/test_profile_state_service.py
  ```
- [ ] **Step 3 — Smoke import gói chat:**
  ```bash
  python -c "import services.chat.conversation_service, services.chat.intent_router; print('ok')"
  ```
- [ ] **Step 4 — Full suite.** `python -m pytest -q` → PASS (số test giảm đúng bằng số test của module đã xóa).
- [ ] **Step 5 — Commit.**
  ```bash
  git commit -m "refactor(dead-code): remove deprecated profile_state_service"
  ```

**Rollback strategy:** `git revert <sha>` khôi phục cả module lẫn test. Không có data path/DB nào phụ thuộc.

---

## Self-Review (đối chiếu với §9 P0 của audit)

| Hạng mục P0 trong audit (§9) | PR phủ |
|---|---|
| Xóa file/hàm chết: `admission_schema.py`, `providers/base.py` | PR5 |
| Xóa hàm `db_writer` chết | PR4 |
| Xóa `parse_hust_programs`, `run_ingestion` | PR1 |
| Xóa `AdvisoryRunRecord`, `index_candidates_by_id`, `detect_conflicts` | PR1 |
| Xóa dòng whitespace divider chết | PR2 |
| Đưa import `intent_router` lên đầu | PR3 |
| Bỏ 5 dependency thừa | PR6 |
| Đổi tên `psycopg2_Binary`→`_to_db_binary`, hoist import | **Thay bằng xóa** ở PR4 (deletion > rewrite; chỉ caller là hàm chết) |
| (Bonus §1) `profile_state_service` chết | PR7 — **gated**, cần duyệt |

**Quyết định để lại P2 (không làm trong P0, có chủ đích):** data path `raw_documents`/`extracted_facts` + `evidence_agent` LEFT JOIN (§1 confidence TB); ABC provider "làm thật hay inline" (§4.2); drop bảng `discovered_resources` (cần migration). P0 chỉ gỡ phần đã chết chắc chắn.

**Nguyên tắc đã tuân thủ:** không big-bang; mỗi PR nhỏ + revert được độc lập; app xanh giữa mỗi PR (smoke import + full suite); ưu tiên xóa hơn viết lại (PR4 thay rename bằng delete); không đụng public API đang dùng (PR7 gate riêng).
