# Giai đoạn 1 — Reasoning Integrity (EC-04, EC-12, EC-13, EC-22, EC-24)

Ngày: 2026-06-04 · Trạng thái: đã duyệt hướng tiếp cận với user · Nguồn yêu cầu: `docs/edge-case.md`

## 1. Bối cảnh & mục tiêu

Đánh giá theo `docs/edge-case.md` cho thấy tầng hội thoại đã vững nhưng tầng nghiệp vụ
tư vấn vi phạm các nguyên tắc cốt lõi: hệ thống vẫn xếp hạng chương trình mà thí sinh
**không đủ điều kiện tổ hợp** (EC-12), so điểm khi **chưa biết phương thức xét tuyển**
(EC-13), nhận điểm **vượt thang** (EC-04), **không reset được hồ sơ** cho người khác
(EC-22), và trả lời chung chung khi **không có kết quả** (EC-24).

Giai đoạn 1 sửa cả 5 mà **không cần migration store** (không đụng `canonical_admission_records`).
Điểm chuẩn (cutoff) là Giai đoạn 2, ngoài phạm vi spec này.

## 2. Phạm vi

**Trong phạm vi:**
- Thêm `admission_method` (mã canonical) vào profile hai tầng (`ChatProfileState`, `StudentProfile`) + slot bắt buộc + trích xuất + validation thang điểm.
- Gate reasoning theo phương thức; loại candidate sai tổ hợp khỏi recommendations, ghi `EligibilityCheck(eligible=False)`.
- Intent RESET hai lớp (deterministic + LLM route) xoá hồ sơ đang tư vấn.
- Explanation: section "Không đủ điều kiện", thông báo no-match minh bạch theo tiêu chí thật.

**Ngoài phạm vi (Giai đoạn 2/3):**
- Cutoff/điểm chuẩn trong store; nhãn BORDERLINE/UNCERTAIN theo cutoff (EC-14/15/16/18).
- Structured tuition/location, strict flag, `__remove__`, `unresolved_major_mentions` (EC-07/08/11/19/20/25).
- Quy đổi điểm giữa các thang. Hệ thống tuyệt đối không tự quy đổi.

## 3. Quyết định thiết kế đã chốt với user

| # | Quyết định | Lựa chọn |
|---|---|---|
| 1 | Vị trí `admission_method` trong luồng thu thập | **Critical slot, luôn hỏi**, ngay sau `total_score` |
| 2 | Thang điểm | **Bảng thang theo phương thức** (30/30/150/100/—); score-fit bonus chỉ cho thang 30 |
| 3 | Candidate khác phương thức user chọn | **Vẫn xếp hạng theo ngành/trường + caution**, không score-fit, không check tổ hợp |
| 4 | Hiển thị NOT_ELIGIBLE | **Section riêng cuối câu trả lời** (cap 3) với lý do tổ hợp cụ thể |
| 5 | RESET | **Xoá ngay + báo đã reset**, không hỏi xác nhận; áp delta cùng lượt lên hồ sơ trắng |

## 4. Thiết kế chi tiết

### WS1 — `admission_method` & validate thang điểm (EC-13, EC-04)

#### 4.1.1 Module mới `services/profile/admission_methods.py`

Nguồn sự thật phía profile cho phương thức xét tuyển:

- `METHOD_CODES = {"thpt_score", "school_record", "competency_test", "combined", "talent_admission"}` — khớp mã trong `ingestion/normalization/dictionaries/methods.json`.
- `SCORE_SCALES: dict[str, float | None] = {"thpt_score": 30.0, "school_record": 30.0, "competency_test": 150.0, "combined": 100.0, "talent_admission": None}` — `None` = không validate trần.
- `THANG_30_METHODS = {"thpt_score", "school_record"}` — chỉ các phương thức này được áp score-fit bonus trong reasoning.
- `parse_admission_method(raw: str) -> Optional[str]`:
  - Load alias một lần lúc import: đọc `methods.json`, gộp alias + `canonical_name` của `_shared` **và mọi section trường** (user chưa nói trường nào nên phải match cả "Đánh giá tư duy", "TSA"...).
  - Bổ sung alias hội thoại: `"diem thi"→thpt_score`, `"thi thpt"→thpt_score`, `"tot nghiep"→thpt_score`, `"hoc ba"→school_record`, `"dgnl"/"danh gia nang luc"/"hsa"→competency_test`, `"dgtd"/"tu duy"/"tsa"→competency_test`, `"ket hop"→combined`, `"tuyen thang"/"tai nang"/"uu tien xet tuyen"→talent_admission`.
  - So khớp trên `normalize_text(raw)` (bỏ dấu, lowercase — tái dùng `services/profile_service.normalize_text`); alias cũng được normalize. Phrase containment, **alias dài nhất thắng** (tránh "điểm thi" ăn nhầm trong câu nói về "điểm thi đánh giá năng lực" — alias dài hơn "đánh giá năng lực" thắng). Alias ngắn ≤3 ký tự (TSA, HSA) dùng word-boundary như pattern `_contains_alias` hiện có.
  - Không match → `None`.
- `method_display(code: str) -> str` — nhãn tiếng Việt trung lập theo trường: `thpt_score→"điểm thi tốt nghiệp THPT"`, `school_record→"học bạ"`, `competency_test→"đánh giá năng lực / tư duy"`, `combined→"xét tuyển kết hợp"`, `talent_admission→"xét tuyển tài năng / tuyển thẳng"`.
- `candidate_method_codes(candidate: CandidateProgram) -> Optional[set[str]]`:
  - Store lưu `admission_method` là **display name**, có thể ghép nhiều phương thức bằng `;` (xem `ingestion/normalization/normalizer.py:46-55`).
  - Dùng `ingestion.normalization.method_mapper.map_method(display, school_id=candidate.school_id)` map ngược → chuỗi mã `;`-joined → split thành set. Kết quả chứa phần tử ∉ `METHOD_CODES` (map_method trả raw khi không match) hoặc input rỗng → trả `None` (= unknown, **không gate**, xử lý như đúng phương thức + không kết luận).
  - Import `ingestion.normalization` từ `services` đã có tiền lệ (`state.py` import `ingestion.config.settings`); bọc try/except trả `None` khi lỗi.

#### 4.1.2 Slot mới + parser

`services/profile/slots.py`:

- Thêm `Slot("admission_method", critical=True, order=2, follow_up="Em xét tuyển theo phương thức nào: điểm thi tốt nghiệp THPT, học bạ, đánh giá năng lực hay xét tuyển kết hợp?", parser=parse_admission_method)`.
- Đánh lại order: `admission_year=0, total_score=1, admission_method=2, preferred_majors=3, subject_combination=4, location_preference=5, tuition_budget=6`. `SLOTS` là nguồn duy nhất nên mọi nơi (missing slots, follow-up, correction detector, extractor render) tự cập nhật.
- **Sửa `parse_score`**: regex `(?<!\d)\d{1,3}(?:[.,]\d+)?(?!\d)`, sanity cap `[0, 150]`. Sửa được 2 lỗi: (a) điểm ĐGNL 3 chữ số ("105") parse được; (b) "2026" không còn bị cắt thành `20` (lookaround chặn token 4 chữ số) — trước đây nếu pending slot là `total_score` mà user trả lời năm, điểm rác 20.0 lọt vào profile.

Hệ quả tự nhiên (không cần code thêm): `admission_method` nằm trong `_ORDERED_CRITICAL` của `conversation_service` → **sửa phương thức sau khi đã có kết quả tự kích hoạt correction re-run** (AC EC-05 mở rộng cho phương thức).

#### 4.1.3 Models & mapping

- `services/chat/models.py::ChatProfileState` += `admission_method: Optional[str] = None`.
- `agents/models.py::StudentProfile` += `admission_method: Optional[str] = None`.
- `services/chat/advisory_runner.py::run_advisory_for_session` map thêm field này.
- `services/profile/extractor.py`:
  - `_LLM_SLOT_KEYS` += `"admission_method"`.
  - `STATE_UPDATE_PROMPT` += dòng `- admission_method: một trong "thpt_score" | "school_record" | "competency_test" | "combined" | "talent_admission"` và sửa mô tả total_score thành `số (0..150 tuỳ phương thức; thang phổ biến là 30)`.
  - `_coerce_llm_delta`: giá trị `admission_method` ∉ `METHOD_CODES` → thử `parse_admission_method(value)` (LLM hay trả display name tiếng Việt); vẫn không ra → drop key.
- `services/profile_inference_service.py::PROFILE_SYSTEM_PROMPT` (đường profile_agent cho pipeline-direct) += instruction tương tự.

#### 4.1.4 Validation `services/profile/validation.py` (mới)

```python
def validate_profile_delta(delta: dict, current: ChatProfileState) -> tuple[dict, list[dict]]
```

Pure function, trả `(clean_delta, rejections)`; mỗi rejection là `{"slot", "value", "message"}` với message template tiếng Việt sẵn dùng.

- **R1 — điểm vượt thang**: `delta` có `total_score` (scalar), phương thức hiệu lực = `delta.get("admission_method") or current.admission_method`, có scale và `score > scale` → loại `total_score` khỏi clean_delta, message: *"Với phương thức {display} (thang {scale}), tổng điểm {score} chưa hợp lệ. Em kiểm tra lại điểm hoặc cho mình biết em đang dùng phương thức xét tuyển nào nhé."* (khớp response mẫu EC-04).
- **R2 — phương thức mới làm điểm cũ vô lệ**: `delta` có `admission_method`, `current.total_score` vượt scale mới → giữ `admission_method`, thêm `total_score = None` vào clean_delta (missing_slots tự tính lại → hệ thống hỏi lại điểm), message: *"Em chọn phương thức {display} (thang {scale}) nhưng điểm {score} đã ghi trước đó vượt thang này, nên mình xoá điểm cũ. Điểm của em theo phương thức này là bao nhiêu?"*
- Phương thức chưa biết (cả delta lẫn current đều None) → không validate trần (chỉ còn sanity [0,150] của parser); EC-13 xử lý phần "chưa so cutoff" ở reasoning.

**Điểm tích hợp duy nhất** — `conversation_service.handle_user_message`, ngay sau `_deterministic_safety_net` (cả 3 nhánh continue-advisory / correction-rerun / advisory dùng chung delta nên 1 điểm chèn phủ hết, kể cả "em nhầm, 35 điểm" sau khi đã có kết quả):

```python
delta = self._deterministic_safety_net(delta, content, active_slot)
clean_delta, rejections = validate_profile_delta(delta, profile_state)
if rejections:
    return self._handle_rejection(session_token, profile_state, flow_state, clean_delta, rejections)
# ... các nhánh hiện có dùng clean_delta thay cho delta
```

`_handle_rejection`: áp `clean_delta` (phần hợp lệ vẫn được ghi) với status `"collecting_profile"`, response = message của rejection đầu tiên, `kind="assistant_validation"`. Đồng thời set flow `ADVISORY_FLOW` + `pending_question` = `follow_up` của slot bị từ chối — bắt buộc, vì rejection có thể xảy ra cả khi flow đã completed (correction "em nhầm, 35 điểm"); có pending_question thì câu trả lời cụt kế tiếp ("28") mới được `_maybe_continue_advisory` nhận qua safety-net parser. Message từ chối tự nó là câu re-ask — không lặp lại câu hỏi gốc máy móc.

### WS2 — Reasoning trung thực (EC-12, EC-13)

`services/reasoning_service.py::reason_candidates` — mỗi candidate đi 1 trong 3 ngả:

1. **Khác phương thức** (`profile.admission_method` có giá trị, `candidate_method_codes(candidate)` có giá trị, và code profile ∉ codes candidate):
   - KHÔNG check tổ hợp (tổ hợp của row thuộc phương thức khác), KHÔNG score bonus.
   - Score chỉ từ major (0.35) + school (0.15) → tự xếp dưới row đúng phương thức (thiếu +0.40).
   - Caution: *"Chương trình này xét theo {display ứng viên (raw)}, khác phương thức em đã chọn ({method_display(profile)}). Điểm và tổ hợp chưa được đối chiếu."*
   - `EligibilityCheck(eligible=None)`.
2. **Đúng phương thức (hoặc một bên unknown) + tổ hợp KHÔNG khớp** (profile có combination, candidate có list không rỗng, combination ∉ list):
   - `EligibilityCheck(eligible=False, risks=["Chương trình không nhận tổ hợp {X} theo phương thức đã chọn — các tổ hợp được công bố: {list}."])`.
   - **`continue` — KHÔNG append vào `recommendations`** (sửa gốc EC-12: trước đây vẫn append với band tính từ score còn lại, tối đa 0.60 → "match").
3. **Đúng phương thức + tổ hợp hợp lệ/chưa khai**: logic hiện tại, với thay đổi:
   - Score bonus `>=26/+0.10`, `>=24/+0.05` **chỉ khi** phương thức hiệu lực ∈ `THANG_30_METHODS`.
   - Phương thức ∈ {competency_test, combined, talent_admission} → caution *"Điểm theo {display} chưa thể đối chiếu trực tiếp với dữ liệu tham chiếu hiện có."*
   - Phương thức `None` (gọi pipeline trực tiếp, profile chưa qua slot gate) → không bonus + caution *"Hồ sơ chưa rõ phương thức xét tuyển nên chưa đánh giá mức điểm."* (defense-in-depth cho EC-13).

`services/policy_service.py`:
- `CRITICAL_PROFILE_SLOTS` += `"admission_method"` (warning bổ sung hồ sơ + `requires_follow_up` tự phủ).
- `profile.admission_method is None` → blocked_claims += `"no_score_fit_without_method"`.
- Flag mới `"no_eligible_recommendations"` khi `candidates` không rỗng nhưng `recommendations` (đầu vào, từ reasoning) rỗng — phân biệt với `empty_retrieval` (retrieval trả 0 row).

Lưu ý wiring: `policy_agent` ghi đè `state.ranked_recommendations` bằng danh sách lọc — các candidate NOT_ELIGIBLE **không đi qua kênh recommendations** mà đi qua `state.eligibility_checks` (đã có sẵn trên state + tracing extractor, hiện không ai dùng downstream → giờ explanation dùng).

### WS3 — RESET hồ sơ (EC-22)

Hai lớp phát hiện, một handler:

- **Lớp deterministic** — `_is_reset_request(content)` trong `conversation_service`: match cụm normalize (`normalize_text`): `"xoa thong tin"`, `"xoa ho so"`, `"xoa het"`, `"bat dau lai"`, `"lam lai tu dau"`, `"tu van lai tu dau"`, `"reset"`. Danh sách CỐ Ý hẹp (động từ xoá/làm lại tường minh) để tránh false positive; cách nói mềm để LLM bắt.
  - Đặt **trước** `_maybe_continue_advisory` trong `handle_user_message` — chặn kịch bản hijack: đang chờ `admission_year`, user nói "Xoá hết đi, tư vấn cho em gái em, năm 2026" → safety-net parse được năm → nếu không chặn, `_maybe_continue_advisory` nuốt "2026" và tiếp tục flow với **hồ sơ cũ**.
- **Lớp LLM** — route mới `RESET_PROFILE` trong `intent_router` (thêm vào `Literal` + prompt: mô tả "yêu cầu xoá hồ sơ/bắt đầu lại/tư vấn cho người khác" + few-shot `"Xoá thông tin cũ đi, tư vấn cho em gái em" → {"route":"RESET_PROFILE"}`, `"Giờ tư vấn cho bạn em nhé, hồ sơ khác" → RESET_PROFILE`). Dispatch trong `handle_user_message` → cùng handler.

`_handle_reset(session_token, delta, flow_state)`:
1. `fresh = ChatProfileState()`.
2. `clean_delta, _ = validate_profile_delta(delta, fresh)` — delta của CHÍNH lượt này áp lên hồ sơ trắng (user kèm "năm 2026" thì khỏi hỏi lại năm). Rejection ở đây hiếm (thang chưa biết) — bỏ qua rejection, chỉ áp phần hợp lệ.
3. `merged = apply_profile_delta(fresh, clean_delta)`.
4. Ghi `update_profile_state(token, merged, "collecting_profile")`; flow `ADVISORY_FLOW` + `pending_question` = câu hỏi slot thiếu đầu tiên.
5. Response: `"Mình đã bắt đầu hồ sơ tư vấn mới. {follow_up}"` (khớp response mẫu EC-22). `kind="assistant_follow_up"`.

Không xoá `chat_messages` (lịch sử hội thoại giữ); `latest_run_id` giữ nguyên — an toàn với correction detector vì sau reset mọi `previous` đều None (không bao giờ bị coi là correction).

### WS4 — Explanation minh bạch (EC-12 hiển thị, EC-24)

`services/explanation_service.py::build_explanation` nhận thêm tham số `eligibility_checks: Optional[List[EligibilityCheck]] = None`; `agents/explanation_agent.py` truyền `state.eligibility_checks`.

- **Section "Không đủ điều kiện xét tuyển"** — đặt sau danh sách đề xuất, trước Nguồn tham chiếu. Render từ checks có `eligible is False`, join candidate qua `candidate_id` (dùng `candidates_by_id` sẵn có), dedupe theo (school, program), cap 3:
  ```
  **Không đủ điều kiện xét tuyển**
  - {school_name} — {program_label}: {risks[0]}
  ```
  Chỉ render khi có ít nhất 1 mục.
- **No-match minh bạch** (thay dòng `"Chưa có đề xuất phù hợp từ dữ liệu hiện tại."`): khi `renderable` rỗng, compose deterministic:
  1. Liệt kê tiêu chí ĐANG áp từ profile + admission_year (chỉ field có giá trị): năm, phương thức (display), điểm, tổ hợp, ngành, khu vực, ngân sách.
  2. *"Mình chưa tìm thấy chương trình đáp ứng đồng thời các tiêu chí trên trong dữ liệu hiện có."*
  3. Gợi ý nới ĐÚNG tiêu chí đang set, ưu tiên theo nguyên nhân:
     - Có check `eligible=False` (mọi thứ bị loại vì tổ hợp) → *"Các chương trình ngành {majors} hiện không nhận tổ hợp {X}; em có thể cân nhắc tổ hợp khác hoặc ngành gần."*
     - Policy flag `empty_retrieval` → gợi ý nới ngành/khu vực/ngân sách (chỉ nêu tiêu chí thật sự đang set).
  4. Tuyệt đối không bịa chương trình; không tự nới constraint — chỉ GỢI Ý nới.
- `_SLOT_LABELS` += `"admission_method": "phương thức xét tuyển"` (correction message tự đúng khi user sửa phương thức).
- `_intro_paragraph` += fact `f"phương thức {method_display(...)}"` khi có.

## 5. Data flow sau thay đổi

```
user msg → extract delta (LLM + safety-net) → [RESET pre-check] → validate (R1/R2)
  → rejection? → trả message từ chối + áp phần hợp lệ (DỪNG)
  → continue-advisory / correction-rerun / intent route (RESET_PROFILE mới)
  → ... → status ready → advisory run:
profile → retrieve (không đổi) → conflict (không đổi)
  → reason: 3 ngả method-mismatch / NOT_ELIGIBLE (checks-only) / scored
  → policy: +admission_method critical, +no_eligible_recommendations, +no_score_fit_without_method
  → explain: +section Không đủ điều kiện, +no-match minh bạch, +method trong intro
```

## 6. Error handling

- `parse_admission_method` / `candidate_method_codes` lỗi hoặc không map được → `None` → hệ thống về hành vi "unknown method" (không gate, có caution) — degrade graceful, không raise.
- LLM extractor trả admission_method rác → coerce qua parser → drop nếu vẫn rác.
- Gateway lỗi ở intent router → fallback hiện tại là `ADVISORY_FLOW`; reset deterministic vẫn hoạt động khi LLM chết.
- Validation là pure function — không I/O, không thể fail runtime ngoài bug.

## 7. Testing (TDD per slice)

Tất cả unit, fake gateway theo pattern test hiện có, không cần DB:

1. `tests/services/profile/test_admission_methods.py` — parse (alias có dấu/không dấu, TSA word-boundary, longest-wins, không match → None), display, scales, candidate_method_codes (display ghép `;`, school-specific, không map được → None).
2. `tests/services/profile/test_validation.py` — R1 (35/thang30 reject + giữ field khác trong delta), R2 (đổi method làm điểm cũ vô lệ → score=None), method-unknown không chặn, message templates.
3. `tests/services/profile/test_slots.py` (mở rộng) — slot order mới, parse_score regex mới ("105" ok, "2026" → None, "26,5" ok), follow_up method.
4. `tests/services/chat/test_conversation_service.py` (mở rộng) — EC-13 flow ("27 điểm" → hỏi phương thức), EC-04 reject + re-ask, correction-thành-điểm-vô-lệ bị chặn, reset deterministic, reset hijack guard (pending year + "xoá hết... năm 2026" → hồ sơ mới với year=2026, KHÔNG giữ điểm cũ), RESET_PROFILE route dispatch.
5. `tests/services/test_reasoning_service.py` / `tests/agents/test_reasoning_agent.py` (mở rộng + sửa fixture) — EC-12 (sai tổ hợp → không có trong recommendations, có check eligible=False với reason chứa list tổ hợp), method-mismatch (vẫn rank + caution + không bonus), thang-30 bonus gating, method None caution.
6. `tests/services/test_policy_service.py` — critical slot mới, 2 flag/claim mới.
7. `tests/services/test_explanation_service.py` — section Không đủ điều kiện, no-match liệt kê đúng tiêu chí đang set, intro có phương thức.
8. `tests/e2e/test_advisory_flow.py` (sửa fixture + mở rộng) — happy path với admission_method; no-match path mới.

**Fixture vỡ có chủ đích:** mọi `StudentProfile`/`ChatProfileState` fixture thiếu `admission_method` sẽ kéo theo warning policy / caution reasoning / hỏi thêm slot — các test hiện có phải bổ sung `admission_method="thpt_score"` (và candidate fixture cần `admission_method="Xét điểm thi TN THPT"`) để giữ hành vi cũ.

## 8. Tương thích ngược

- Session cũ trong DB thiếu key `admission_method` → Pydantic default `None` → lượt chat kế tiếp tự hỏi bổ sung phương thức (hành vi mong muốn, không cần migrate).
- `result_json` của run cũ không đổi schema (chỉ thêm nội dung text trong final_answer các run mới).
- Không thay đổi schema DB, không migration.

## 9. File inventory

| File | Thay đổi |
|---|---|
| `services/profile/admission_methods.py` | MỚI — codes, scales, parse, display, candidate codes |
| `services/profile/validation.py` | MỚI — validate_profile_delta R1/R2 |
| `services/profile/slots.py` | slot mới, renumber order, sửa parse_score |
| `services/profile/extractor.py` | prompt + allow-list + coerce method |
| `services/chat/models.py` | ChatProfileState += admission_method |
| `agents/models.py` | StudentProfile += admission_method |
| `services/chat/advisory_runner.py` | map field mới |
| `services/profile_inference_service.py` | prompt += admission_method |
| `services/chat/conversation_service.py` | validation hook, _handle_rejection, reset pre-check, _handle_reset, dispatch RESET_PROFILE |
| `services/chat/intent_router.py` | route RESET_PROFILE + prompt |
| `services/reasoning_service.py` | 3 ngả method/eligibility/scored |
| `services/policy_service.py` | critical slot, flags, claims |
| `services/explanation_service.py` | eligibility section, no-match, intro, labels |
| `agents/explanation_agent.py` | truyền eligibility_checks |
| `tests/...` | theo mục 7 |
