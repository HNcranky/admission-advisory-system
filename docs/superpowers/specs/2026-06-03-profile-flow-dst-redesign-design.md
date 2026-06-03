# Thiết kế: Dựng lại luồng phân tích hồ sơ theo hướng DST

- **Ngày:** 2026-06-03
- **Trạng thái:** Draft (chờ review)
- **Phạm vi:** Tầng phân tích/thu thập hồ sơ (`profile`) của trợ lý tư vấn tuyển sinh
- **Động lực gốc:** Trích xuất `preferred_majors` đang phụ thuộc danh sách `program_id` hardcode trong prompt → thêm ngành mới là hỏng.

---

## 1. Bối cảnh & vấn đề

Luồng hiện tại, mỗi lượt chat trong advisory:

```
handle_user_message (services/chat/conversation_service.py)
 ├─ _maybe_continue_advisory ──► extract_profile(content)   [LLM #1]
 ├─ intent_router.classify ─────► gateway.run(...)          [LLM #2]
 └─ _handle_advisory ───────────► extract_profile(content)  [LLM #3]  (cùng message với #1)
        └─ merge_profile_state (or-merge) → hỏi slot thiếu kế tiếp
```

`extract_profile` → `build_profile_with_gateway` (`services/profile_inference_service.py`) gọi LLM extract **toàn bộ slot chỉ từ 1 câu hiện tại**, fallback rule-based.

Các điểm yếu đã kiểm chứng:

1. **`preferred_majors` không scale.** Prompt nhồi `MAJOR_ID_GUIDE` (~25 id) + map cứng `INTEREST_MAJOR_MAP`. Thêm ngành phải sửa prompt/map; prompt phình theo số ngành.
2. **Gọi LLM trùng lặp.** `_maybe_continue_advisory` và `_handle_advisory` cùng extract trên một message; trường hợp xấu = 3 LLM call/lượt (extract + classify + extract).
3. **Extract stateless, context-free.** Không truyền state đã biết / slot đang hỏi vào prompt → phải vá bằng `parse_pending_slot_answer` (chỉ lo `total_score`).
4. **~3 định nghĩa "slot thiếu" lệch nhau.** `missing_slots` của LLM (8 key) vs `build_profile` ({total_score, subject_combination, preferred_majors}) vs `CRITICAL_SLOT_ORDER` ({admission_year, total_score, preferred_majors, location_preference}). `subject_combination` — thứ `retrieval_agent` thực sự lọc — **không** nằm trong slot critical nên có thể không bao giờ được hỏi.
5. **Merge bằng `or`** (`extracted.X or current.X`): không sửa/đính chính được giá trị đã có; list bị ghi đè.
6. **Logic ánh xạ ngành rải rác 3 nơi:** `INTEREST_MAJOR_MAP`, alias dictionary (`programs.json`), special-case HUST/UET.

## 2. Mục tiêu / Ngoài phạm vi

**Mục tiêu**
- G1. Thêm ngành/`program_id` mới **không phải sửa prompt hay map tay**; prompt LLM **không phình** theo số ngành.
- G2. Mỗi lượt chỉ **một** lần trích xuất hồ sơ; bỏ double-extract.
- G3. Trích xuất **có state** (state-update) thay vì stateless per-message.
- G4. **Một** nguồn định nghĩa slot duy nhất; `subject_combination` được đặt đúng chỗ.
- G5. Merge cho phép **sửa/đính chính** slot.
- G6. Mọi call LLM/embedding **degrade gracefully** (convention CLAUDE.md): fallback deterministic + `logger.warning`.

**Ngoài phạm vi (non-goals)**
- Không gộp intent-classification vào extraction (giữ tách, chỉ ghi nhận là tối ưu tương lai).
- Không đổi pipeline advisory phía sau profile (`retrieve → conflict → reason → policy → explain`).
- Không làm "explicit clear-to-empty" (user chủ động xóa 1 slot về rỗng) trong v1 — ghi ở §10.
- Không fine-tune model; chỉ dùng prompting + retrieval.

## 3. Cơ sở nghiên cứu

Tổng hợp từ deep-research (24/25 claim verify 3-0). Nguồn chính:

- **Diable** (ACL Findings 2023, `arxiv.org/abs/2305.17020`): DST seq2seq tái sinh toàn bộ state mỗi lượt là *kém hiệu quả khi số slot lớn / hội thoại dài*; cập nhật incremental nhanh hơn ~2.4×. → **G2/G3**.
- **State-Update Prompting** (`arxiv.org/pdf/2509.17766`): tái dựng state thay vì nối toàn bộ history → giảm ~59% token / ~73% latency (directional, đo trên multi-hop QA). → **G3**.
- **FnCTOD** (NAACL/ACL 2024, `arxiv.org/abs/2402.10466`) + **OpenAI Structured Outputs** (`developers.openai.com/api/docs/guides/structured-outputs`): DST = structured-output/function-calling theo schema. → extractor schema-driven.
- **Rasa CALM** (`rasa.com/docs/reference/config/components/llm-command-generators/`): *flow retrieval* — chỉ đưa top-matching options vào prompt nên "input context **không** scale tuyến tính theo quy mô assistant"; `minimize_num_calls` — **bỏ qua LLM** khi component rẻ hơn đã điền slot. → **G1** (retrieval thay hardcode) + tiered/deterministic-first.
- **GLiNER+LLM hybrid** (`arxiv.org/pdf/2411.18980`): bộ lọc deterministic thu hẹp tập slot trước khi gọi LLM (+34% F1 vs +2% nếu chỉ deterministic). → tiered resolver.
- **Rasa/Azure CLU**: collect 1 slot đang thiếu mỗi bước, chỉ hỏi slot còn thiếu. → **G4**.

## 4. Kiến trúc đích — "DST-style profile flow"

5 thành phần, mỗi cái một trách nhiệm, test độc lập:

| # | Thành phần | File (đề xuất) | Trách nhiệm |
|---|---|---|---|
| 1 | **Slot registry** | `services/profile/slots.py` | 1 nguồn: danh sách slot, critical, thứ tự, câu follow-up, parser deterministic, `missing_critical_slots`, `next_follow_up_question` |
| 2 | **Program catalog + embeddings** | `services/profile/major_catalog.py` + migration `015` | Suy danh mục ngành từ `canonical_admission_records` (+ alias `programs.json`), embed, lưu `program_catalog_embeddings` |
| 3 | **Tiered major resolver** | `services/profile/major_resolver.py` | Tier1 alias → Tier2 embedding top-K → Tier3 LLM chọn trong shortlist |
| 4 | **DST extractor** | `services/profile/extractor.py` | 1 call/lượt, structured-output, state-update, deterministic-first, ủy thác ngành cho (3), trả **delta** |
| 5 | **Orchestration cleanup** | `services/chat/conversation_service.py` | Extract đúng 1 lần/lượt; merge correction-aware (delta) |

> Các module `services/profile_*` cũ (`profile_service.py`, `profile_inference_service.py`) sẽ được rút gọn/di chuyển logic còn dùng vào `services/profile/` và xóa phần hardcode. Giữ shim tạm nếu có import ngoài.

### Data flow một lượt (sau khi xong cả 3 slice)

```
user message
  │
  ▼
load ChatProfileState (known_state) + flow_state
  │
  ▼
[active_slot = missing_critical_slots(known_state)[0] nếu đang advisory]
  │
  ▼
Tier-0 deterministic parse slot đang chờ  ──(điền được, bare answer)──► skip LLM ─┐
  │ (không điền được / câu tự do)                                                 │
  ▼                                                                               │
DST extractor: 1 LLM call structured-output                                       │
  - input: known_state (đã điền) + danh sách slot còn thiếu                       │
  - output: DELTA (chỉ slot thay đổi lượt này)                                    │
  - preferred_majors KHÔNG do LLM sinh id → gọi resolve_majors(message,state)     │
        Tier1 alias → Tier2 pgvector top-K → Tier3 LLM chọn trong K              │
  ▼                                                                               │
apply_profile_delta(known_state, delta) ◄───────────────────────────────────────┘
  ▼
missing = missing_critical_slots(merged)
  ├─ còn thiếu → hỏi next_follow_up_question(merged)
  └─ đủ → should_start_run = True
```

`intent_router.classify` vẫn chạy như cũ cho các message không phải "trả lời slot đang chờ" (giữ tách biệt — non-goal).

---

## 5. Slice 1 — Slot registry (nền)

**Mục tiêu:** gộp 3 định nghĩa slot lệch nhau về một nguồn. Không đổi hành vi LLM.

```python
# services/profile/slots.py
from dataclasses import dataclass
from typing import Any, Callable, Optional

@dataclass(frozen=True)
class Slot:
    name: str
    critical: bool            # phải có trước khi chạy advisory
    order: int                # thứ tự hỏi
    follow_up: str            # câu hỏi follow-up tiếng Việt
    parser: Optional[Callable[[str], Any]] = None  # parse câu trả lời cụt cho slot này

SLOTS: list[Slot] = [
    Slot("admission_year", critical=True,  order=0, follow_up="Bạn đang xét tuyển cho năm nào?", parser=parse_admission_year),
    Slot("total_score",    critical=True,  order=1, follow_up="Tổng điểm hoặc mức điểm ước tính của bạn là bao nhiêu?", parser=parse_score),
    Slot("preferred_majors", critical=True, order=2, follow_up="Bạn quan tâm nhất đến ngành nào?", parser=None),
    Slot("subject_combination", critical=True, order=3, follow_up="Bạn xét theo tổ hợp nào, ví dụ A00, A01 hay D01?", parser=parse_subject_combination),
    Slot("location_preference", critical=False, order=4, follow_up="Bạn muốn học ở khu vực hoặc thành phố nào?", parser=None),
    Slot("tuition_budget", critical=False, order=5, follow_up="Mức học phí bạn mong muốn khoảng bao nhiêu?", parser=None),
]
# Ghi chú: preferred_schools và constraints KHÔNG nằm trong registry — chúng được
# extractor trích xuất cơ hội (opportunistic) khi user nhắc tới, nhưng không phải slot
# critical nên không có câu follow-up và không chặn việc chạy advisory.

def missing_critical_slots(state) -> list[str]:
    return [s.name for s in sorted(SLOTS, key=lambda s: s.order)
            if s.critical and not getattr(state, s.name, None)]

def next_follow_up_question(state) -> Optional[str]:
    missing = missing_critical_slots(state)
    if not missing:
        return None
    return next(s.follow_up for s in SLOTS if s.name == missing[0])

def parse_slot(name: str, raw_message: str):
    slot = next((s for s in SLOTS if s.name == name), None)
    return slot.parser(raw_message) if slot and slot.parser else None
```

**Quyết định cần xác nhận (§10-A):** đưa `subject_combination` vào **critical**. Lý do: `retrieval_agent` lọc theo nó (`retrieval_agent.py:20`) và nó cần cho xét tổ hợp/điểm chuẩn. Đánh đổi: thêm 1 câu hỏi cho user. Nếu muốn ít ma sát hơn, có thể để `critical=False` và chỉ hỏi khi cần.

**Thay đổi đi kèm:**
- `services/chat/profile_state_service.py`: `CRITICAL_SLOT_ORDER`, `missing_critical_slots`, `next_follow_up_question`, `parse_pending_slot_answer` → import từ `slots.py` (xóa bản trùng).
- `services/profile_service.py::build_profile`, `profile_inference_service.py` (`missing_slots`): tính `missing_slots` qua `slots.py`.
- Parser deterministic chuyển vào `slots.py` (tái dùng `extract_score`, `extract_subject_combination`, regex năm).

**Test:** `missing_critical_slots` cho mọi tổ hợp slot đã/chưa điền; `next_follow_up_question` đúng thứ tự; `parse_slot` cho từng slot (bare answer hợp lệ/không hợp lệ).

## 6. Slice 2 — Catalog + tiered major resolver (giải nỗi đau gốc)

### 6.1 Migration `db/migrations/015_program_catalog_embeddings.sql`

```sql
-- Catalog ngành dùng cho việc ánh xạ free-text -> program_id (semantic retrieval).
-- embedding là vector(768) — phải khớp ingestion.config.settings.EMBEDDING_DIM.
CREATE TABLE IF NOT EXISTS program_catalog_embeddings (
    program_id      TEXT PRIMARY KEY,
    canonical_name  TEXT NOT NULL,
    aliases_text    TEXT NOT NULL DEFAULT '',
    field           TEXT,
    embed_input     TEXT NOT NULL,                 -- chuỗi đã embed (canonical + aliases + field)
    content_hash    TEXT NOT NULL,                 -- sha256(embed_input) để skip re-embed
    embedding       vector(768),                   -- nullable: build-then-embed
    source          TEXT NOT NULL DEFAULT 'canonical',  -- 'canonical' | 'dictionary'
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_program_catalog_embedding
    ON program_catalog_embeddings USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_program_catalog_content_hash
    ON program_catalog_embeddings (content_hash);
```

> Idempotent theo chuẩn `db/migrations`. `program_id` là id canonical (`computer_science`, `software_engineering`…) nên dùng làm PK.

### 6.2 Build catalog — `services/profile/major_catalog.py`

```python
def build_major_catalog(*, connection_factory=..., embedder=None,
                        dictionary_path=...) -> CatalogBuildReport:
    """
    1. Nguồn ngành = DISTINCT (program_id, program_name_canonical) từ
       canonical_admission_records (nguồn chân lý — ngành mới chảy vào khi ingest).
    2. Enrich alias/field từ programs.json nếu khớp program_id (best-effort).
    3. embed_input = f"{canonical_name}. Aliases: {aliases}. Field: {field}".
       content_hash = sha256(embed_input).
    4. Reuse embedding theo content_hash: chỉ embed input mới/đổi
       (GeminiEmbedder.embed(..., task_type="RETRIEVAL_DOCUMENT")).
    5. UPSERT vào program_catalog_embeddings.
    Trả CatalogBuildReport(total, embedded, reused, skipped).
    """
```

- **Trigger refresh:** CLI `python -m services.profile.build_major_catalog`, chạy sau `ingestion.main`. (Tùy chọn: gọi cuối `pipeline/ingestion_pipeline.py` — ghi §10-B để chốt.)
- **Reuse embedding:** theo `content_hash` (giống `chunk_content_hash` của knowledge) → re-build không re-embed ngành không đổi.
- Repository theo pattern `connection_factory` + `_cursor` (convention CLAUDE.md), không hand-roll `conn.close()`.

### 6.3 Tiered resolver — `services/profile/major_resolver.py`

```python
def resolve_majors(text: str, *, known_state=None, top_k: int = 8,
                   score_threshold: float = 0.55, high_threshold: float = 0.70,
                   margin: float = 0.08, gateway=None,
                   embedder=None, repository=None) -> list[str]:
    """Free-text -> list[program_id]. Tiered, deterministic-first."""
    # Tier 1 — alias/exact match trên catalog (rẻ, không LLM/embedding).
    hits = match_aliases(normalize_text(text))          # tái dùng logic programs.json
    if hits:
        return dedupe(hits)

    # Tier 2 — embedding retrieval top-K từ DB (scale vô hạn theo catalog).
    emb = embedder.embed([text], task_type="RETRIEVAL_QUERY")[0]
    candidates = repository.vector_search_programs(emb, limit=top_k)   # [(program_id, name, score)]
    strong = [c for c in candidates if c.score >= score_threshold]
    if not strong:
        return []                                       # không đủ tự tin → để extractor xử lý slot khác
    # Nếu top tách biệt rõ (score[0] - score[1] > margin) HOẶC chỉ có 1 ứng viên mạnh
    # → trả thẳng các ứng viên trên ngưỡng cao (có thể >1 ngành liên quan), skip LLM.
    if confident(strong):
        return [c.program_id for c in strong if c.score >= high_threshold] or [strong[0].program_id]

    # Tier 3 — LLM chọn TẬP CON liên quan trong shortlist K (prompt KÍCH THƯỚC CỐ ĐỊNH = K,
    # không phải toàn catalog). Có thể trả nhiều program_id.
    try:
        return llm_pick_from_shortlist(text, strong, gateway)   # -> list[program_id]
    except InferenceError:
        logger.warning("major resolver Tier3 LLM failed, dùng top embedding")
        return [strong[0].program_id]
```

- `vector_search_programs`: `SELECT program_id, canonical_name, 1 - (embedding <=> %s::vector) AS score FROM program_catalog_embeddings WHERE embedding IS NOT NULL ORDER BY embedding <=> %s::vector LIMIT %s` (mẫu giống `KnowledgeChunkRepository.vector_search`).
- `minimize_num_calls`: Tier3 chỉ chạy khi Tier1 rỗng **và** Tier2 mơ hồ.
- **Degrade:** embedder lỗi → trả `[]` (extractor vẫn chạy các slot khác) + `logger.warning`. Không bao giờ raise lên caller.
- Xóa `INTEREST_MAJOR_MAP`, `MAJOR_ID_GUIDE`, special-case HUST/UET ở `build_profile`.

**Test:** Tier1 khớp alias rõ ("kỹ thuật phần mềm" → `software_engineering`); Tier2 ngụ ý ("em thích làm app" → top-K hợp lý) — dùng embedder fake/seeded; Tier3 chọn đúng trong shortlist (gateway fake); ngưỡng/margin; degrade khi embedder/gateway lỗi; **thêm program_id mới vào catalog → resolve được mà không sửa code/prompt** (test chống hồi quy cho G1).

## 7. Slice 3 — DST extractor + orchestration

### 7.1 Extractor — `services/profile/extractor.py`

```python
def extract_profile_update(message: str, *, known_state, active_slot=None,
                           gateway=None, resolver=resolve_majors) -> dict:
    """Trả DELTA: chỉ các slot thay đổi trong lượt này (DST update)."""
    delta: dict = {}

    # Tier-0: parse câu trả lời cụt cho slot đang chờ (deterministic). Có thể skip LLM.
    if active_slot:
        val = parse_slot(active_slot, message)
        if val is not None:
            delta[active_slot] = val

    # preferred_majors: KHÔNG để LLM sinh id — ủy thác resolver tiered.
    majors = resolver(message, known_state=known_state, gateway=gateway)
    if majors:
        delta["preferred_majors"] = majors

    # Nếu chỉ cần slot đang chờ và đã có (bare answer) → khỏi gọi LLM.
    if active_slot and active_slot in delta and is_bare_answer(message):
        return delta

    # 1 LLM call structured-output, state-update: truyền state đã biết + slot còn thiếu,
    # yêu cầu trả CHỈ slot thay đổi lượt này (trừ preferred_majors do resolver lo).
    try:
        result = gateway.run(InferenceRequest(
            agent_name="profile_extractor",
            task_type="profile_extraction",
            system_prompt=STATE_UPDATE_PROMPT,         # mô tả schema slot, "return only changed"
            user_prompt=render_state_update(known_state, message),  # state + message, KHÔNG nhồi catalog ngành
            output_mode="json", temperature=0.0,
        ))
        delta.update(coerce_slot_updates(result.parsed_data))   # bỏ qua key rỗng/không hợp lệ
    except InferenceError:
        logger.warning("profile extractor LLM failed, dùng delta deterministic")
    return delta
```

- **State-update prompting:** prompt chứa state đã biết + slot còn thiếu (không nối toàn bộ history). Schema slot mô tả trong system prompt (FnCTOD-style), `temperature=0.0`, `output_mode="json"`.
- **preferred_majors decoupled hoàn toàn khỏi prompt** → đạt G1 (prompt không phình theo số ngành).
- **Một** LLM call/lượt (hoặc 0 nếu bare answer điền được slot).

### 7.2 Merge correction-aware

```python
def apply_profile_delta(current, delta: dict):
    merged = current.model_copy(update=delta)   # delta override → sửa/đính chính được
    merged.missing_slots = missing_critical_slots(merged)
    return merged
```

Thay `merge_profile_state` (`extracted.X or current.X`). Vì extractor chỉ trả slot **thay đổi**, `{**current, **delta}` vừa cho phép correction vừa không vô tình xóa slot không nhắc tới.

### 7.3 Orchestration — `conversation_service.py`

- `handle_user_message` tính `active_slot` từ `missing_critical_slots(profile_state)`.
- Gọi `extract_profile_update(...)` **đúng một lần**, truyền delta xuống cả nhánh "continue advisory" lẫn "handle advisory" (bỏ double-extract ở `_maybe_continue_advisory` + `_handle_advisory`).
- Nhánh quyết định tiếp tục advisory vs route khác dựa trên delta + intent (intent vẫn là call riêng — non-goal).

**Test:**
- **G2 (chống hồi quy):** 1 lượt advisory ⇒ `gateway.run` được gọi **đúng 1 lần** cho extraction (đếm call trên gateway fake).
- State-update: lượt 2 trả lời "29" với `active_slot=total_score` ⇒ delta `{total_score: 29.0}`, **không** gọi LLM (Tier-0).
- Correction: đã có `preferred_schools=[hust]`, user "thực ra mình thích NEU hơn" ⇒ merged cập nhật đúng.
- Degrade: gateway/embedder lỗi ⇒ vẫn ra delta deterministic, không crash.

## 8. Tổng hợp thay đổi schema/file

- **Mới:** `db/migrations/015_program_catalog_embeddings.sql`; `services/profile/{__init__,slots,major_catalog,major_resolver,extractor}.py`; tests tương ứng.
- **Sửa:** `services/chat/conversation_service.py`, `services/chat/profile_state_service.py`, `services/profile_service.py`, `services/profile_inference_service.py`, `agents/profile_agent.py` (dùng extractor mới), `db.setup_db` (đăng ký migration 015 nếu cần liệt kê tường minh).
- **Xóa/di trú:** `INTEREST_MAJOR_MAP`, `MAJOR_ID_GUIDE`, special-case HUST/UET, `merge_profile_state` (`or`), bản trùng `CRITICAL_SLOT_ORDER`.

## 9. Error handling & degradation (convention CLAUDE.md)

| Lỗi | Hành vi |
|---|---|
| Embedder lỗi (resolver Tier2) | `resolve_majors` trả `[]`, `logger.warning`; extractor chạy tiếp slot khác |
| Gateway lỗi (resolver Tier3) | Dùng top embedding candidate |
| Gateway lỗi (extractor LLM) | Dùng delta deterministic (Tier-0 + resolver) |
| Catalog rỗng/chưa build | Tier1 alias vẫn chạy; Tier2 trả `[]`; log cảnh báo "catalog chưa build" |
| Migration 015 chưa chạy | `major_catalog`/resolver phát hiện thiếu bảng → degrade Tier1-only + log |

Không call LLM/embedding nào được phép raise lên `conversation_service`.

## 10. Quyết định mở / cần xác nhận khi review

- **A. `subject_combination` critical?** Đề xuất: **có** (retrieval cần). Đánh đổi: +1 câu hỏi.
- **B. Trigger build catalog:** CLI thủ công sau ingest (đề xuất v1) hay hook tự động cuối `ingestion_pipeline`?
- **C. Ngưỡng resolver** `score_threshold`/`high_threshold`/`top_k`/`margin`: đề xuất 0.55 / 0.70 / 8 / 0.08 — cần tinh chỉnh bằng dữ liệu thật (`confident(strong)` = `strong[0].score - strong[1].score > margin` hoặc `len(strong)==1`).
- **D. Explicit clear-to-empty** (user xóa slot): để v2.
- **E. Gộp intent + extraction** thành 1 call: để v2 (giảm thêm 1 LLM call/lượt).

## 11. Thứ tự thi công

1. **Slice 1** (Slot registry) — nền, rủi ro thấp, không đổi hành vi LLM.
2. **Slice 2** (Catalog + resolver) — *ship sớm, giải nỗi đau preferred_majors*; cắm sau extractor hiện tại trước, để bỏ `MAJOR_ID_GUIDE`/`INTEREST_MAJOR_MAP`.
3. **Slice 3** (DST extractor + orchestration) — chuyển sang 1-call/lượt, state-update, merge delta.

Mỗi slice tự test & ship được; có thể tạm dừng sau Slice 2 mà vẫn đạt G1.
