# Giai đoạn 2 — Cutoff Store & Conflict mở rộng (EC-14, EC-15, EC-16, EC-18, + EC-17 display)

Ngày: 2026-06-05 · Trạng thái: đã duyệt hướng tiếp cận với user · Nguồn yêu cầu: `docs/edge-case.md` + audit edge-case 2026-06-05

## 1. Bối cảnh & mục tiêu

Giai đoạn 1 (spec `2026-06-04-phase1-reasoning-integrity-design.md`) đã xử lý EC-04/12/13/22/24.
Audit toàn bộ 25 edge case cho thấy nhóm còn thiếu nặng nhất đều chung một root cause:
**store không có dữ liệu điểm chuẩn (cutoff)** — `canonical_admission_records` chỉ có
quota/tuition/deadline của đề án. Vì vậy:

- **EC-14** (điểm sát ngưỡng → BORDERLINE) — không có cutoff để so.
- **EC-15** (điểm chuẩn biến động qua các năm → UNCERTAIN) — không có chuỗi lịch sử.
- **EC-16** (hai nguồn lệch cutoff → hiển thị cả hai, không chọn lén một nguồn) — không có field để conflict.
- **EC-18** (chỉ có dữ liệu năm cũ → reference_year + caveat) — không có khái niệm năm tham chiếu.
- **EC-17** (lệch quota) hiện PARTIAL: phát hiện + hạ band đúng, nhưng explanation chỉ hiện giá trị
  "winner", không hiện cả hai giá trị kèm nguồn.

Giai đoạn 2 đưa điểm chuẩn lịch sử 2023–2025 vào store theo đúng pattern per-source (migration 010),
cho chảy qua retrieval → conflict → reasoning → explanation, và sửa nốt hiển thị EC-17.

## 2. Phạm vi

**Trong phạm vi:**
- Bảng mới `cutoff_records` (migration **016**) + models + repository write/read.
- Seed curated điểm chuẩn HUST + VNU-UET, phương thức `thpt_score` thang 30, năm 2023–2025,
  mỗi con số kèm `source_url` thật + trust level; một số chương trình demo có ≥2 nguồn để EC-16 có dữ liệu thật.
- Loader CLI `python -m ingestion.ingest_cutoffs` (validate atomic, dry-run, upsert).
- **Một** parser trang chính thức (`hust_cutoff_html`, điểm chuẩn 2025 trên ts.hust.edu.vn) làm proof-of-automation.
- Retrieval attach `cutoff_history` vào `CandidateProgram`.
- Module đánh giá thuần `services/cutoff/assessment.py` (margin/borderline/volatility/conflict semantics).
- Reasoning: bonus theo margin thật thay bonus ngưỡng tuyệt đối khi có dữ liệu; band cap; cautions.
- Conflict: `detect_cutoff_conflicts` + outcome deterministic (không LLM tiebreaker cho cutoff).
- Policy: flag `historical_cutoff_reference`, blocked claim `no_admission_assertion_on_reference_cutoff`.
- Explanation: nhãn score-fit tiếng Việt, dòng tham chiếu per-program, dual-source display,
  caveat toàn cục EC-18; sửa `_data_note` để quota conflict (EC-17) liệt kê đủ giá trị + nguồn.

**Ngoài phạm vi (giai đoạn sau):**
- NEU (chưa có structured ingestion đề án → không có candidate để join).
- Cutoff thang ≠ 30 (ĐGNL/ĐGTD). **Tuyệt đối không quy đổi giữa các thang** (giữ nguyên tắc Phase 1).
- Fallback đề án năm cũ trong retrieval (EC-18 ở phase này = reference_year cho cutoff; retrieval
  không đổi — đề án 2026 đã có trong store, thiếu năm đề án → đường EC-24 hiện có xử lý).
- LLM-fallback extractor cho trang cutoff lạ format (chỉ 1 parser deterministic).
- Cutoff phân biệt theo tổ hợp: assessment bỏ qua tổ hợp (điểm chuẩn lưu kèm list tổ hợp để
  hiển thị, nhưng so sánh theo program+method — eligibility tổ hợp đã được gate EC-12 trước đó).
  Đây là simplification có chủ đích; trường tách điểm theo tổ hợp → seed nhiều entry, xử lý sâu ở phase sau.
- EC-19/20/25 (structured tuition), EC-07/08/11 (remove op, location strict, unresolved mentions) — Giai đoạn 3.

## 3. Quyết định thiết kế đã chốt với user

| # | Quyết định | Lựa chọn |
|---|---|---|
| 1 | Nguồn dữ liệu điểm chuẩn | **Seed tay curated** (mỗi số kèm source_url thật + trust) **+ 1 parser** trang chính thức HUST làm proof; không dùng aggregator |
| 2 | Phạm vi trường/phương thức/năm | **HUST + VNU-UET · chỉ `thpt_score` thang 30 · 2023–2025** (EC-15 cần ≥3 năm) |
| 3 | Phạm vi EC-18 | **Chỉ reference_year cho cutoff**; không fallback năm trong retrieval |
| 4 | Mô hình lưu trữ | **Bảng riêng `cutoff_records`** per-source. Loại phương án nhét `metadata` JSONB (re-crawl đề án sẽ wipe vì `db_writer` upsert `metadata = EXCLUDED.metadata`); loại phương án row `admission_year` quá khứ (lạm dụng ngữ nghĩa, vô hình với filter năm, loạn conflict grouping) |
| 5 | Ngữ nghĩa conflict cutoff | **Không bao giờ LLM pick-winner.** Decision-changing → `unresolved` + nhãn bảo thủ + hiển thị đủ giá trị/nguồn; không decision-changing → `resolved` theo trust nhưng rationale/hiển thị vẫn nêu đủ giá trị |

## 4. Thiết kế chi tiết

### WS1 — Store & models

#### 4.1.1 Migration `db/migrations/016_cutoff_records.sql`

```sql
CREATE TABLE IF NOT EXISTS cutoff_records (
    id                     SERIAL PRIMARY KEY,
    school_id              TEXT NOT NULL,
    program_id             TEXT,
    program_name_canonical TEXT,
    program_name_raw       TEXT,
    cutoff_year            INTEGER NOT NULL,
    admission_method       TEXT NOT NULL,       -- mã canonical: 'thpt_score' (KHÁC convention display của canonical_admission_records)
    score_scale            NUMERIC,             -- 30
    cutoff_score           NUMERIC NOT NULL,
    subject_combinations   JSONB,
    note                   TEXT,                -- tiêu chí phụ: "TTNV <= 2"...
    source_url             TEXT NOT NULL,
    source_trust_level     INTEGER,
    confidence_score       REAL,
    ingested_at            TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (school_id, cutoff_year, program_id, admission_method, source_url)
);

CREATE INDEX IF NOT EXISTS idx_cutoff_school_program
    ON cutoff_records (school_id, program_id, admission_method);
CREATE INDEX IF NOT EXISTS idx_cutoff_school_year
    ON cutoff_records (school_id, cutoff_year);
```

Unique key per-source mirror đúng migration 010 → hai nguồn cùng tồn tại thành hai row (nền của EC-16).
Idempotent (`IF NOT EXISTS`) theo convention migrations hiện có.

#### 4.1.2 Models

- `ingestion/models/pipeline_models.py` thêm:
  - `ExtractedCutoffFact` — mirror `ExtractedAdmissionFact`: `school_name`, `cutoff_year: int`,
    `program_name?`, `program_code?`, `admission_method_raw?`, `subject_combinations_raw?`,
    `cutoff_score_raw: str`, `note_raw?`, `source_reference: SourceReference`,
    `confidence_score`, `extraction_method`.
  - `NormalizedCutoffRecord` — `school_id`, `program_id?`, `program_name_canonical?`,
    `program_name_raw?`, `cutoff_year`, `admission_method` (code), `score_scale: float`,
    `cutoff_score: float`, `subject_combinations: List[str]`, `note?`, `source_url`,
    `source_trust_level`, `confidence_score`.
- `agents/models.py` thêm:
  - `CutoffEntry`: `cutoff_year: int`, `admission_method: str`, `cutoff_score: float`,
    `score_scale: Optional[float]`, `source_url: str`, `trust_level: Optional[int]`, `note: Optional[str]`.
  - `CandidateProgram` += `cutoff_history: List[CutoffEntry] = Field(default_factory=list)` (additive, fixture cũ không vỡ).
  - `CutoffAssessment` (schema ở WS4) — đặt trong `agents/models.py` cạnh `CutoffEntry`:
    `services/cutoff/assessment.py` đã import `CutoffEntry` từ `agents.models`, nên model kết quả
    cũng nằm ở `agents.models` để tránh vòng import services↔agents.
  - `RankedRecommendation` += `cutoff_assessment: Optional[CutoffAssessment] = None`.

### WS2 — Seed curated + loader CLI + parser

#### 4.2.1 Seed `ingestion/cutoff/seeds/cutoff_2023_2025.json`

Mỗi entry một con số điểm chuẩn:

```json
{
  "school_id": "hust",
  "program_name_raw": "Khoa học máy tính",
  "program_code_raw": "IT1",
  "cutoff_year": 2025,
  "admission_method": "thpt_score",
  "score_scale": 30,
  "cutoff_score": 28.25,
  "subject_combinations": ["A00", "A01"],
  "note": "TTNV <= 2",
  "source_url": "https://ts.hust.edu.vn/...",
  "source_trust_level": 5
}
```

- Phủ: HUST + VNU-UET × 2023/2024/2025 × các chương trình đã có trong `canonical_admission_records`
  (ưu tiên nhóm CNTT/KHMT/KHDL khớp kịch bản demo).
- **EC-16 cần conflict thật**: với ≥2 chương trình demo, seed thêm entry thứ hai cùng
  `(school, program, year, method)` từ nguồn chính thức khác (vd trang trường vs đề án PDF/cổng ĐHQG).
- Số liệu tra tay từ trang chính thức lúc soạn seed; mỗi số phải dán đúng URL nguồn — **không bịa**.

#### 4.2.2 Loader CLI `python -m ingestion.ingest_cutoffs`

- Flags: `--seed [path]` (default file trên), `--school <id>`, `--dry-run`, `--source <source_id>` (đường parser, xem 4.2.3).
- **Validate atomic trước khi ghi**: resolve `program_name_raw`/`program_code_raw` → `program_id`
  qua `map_program(..., school_id=...)` sẵn có; `admission_method ∈ METHOD_CODES`;
  `0 < cutoff_score <= score_scale`; `cutoff_year` trong [2020, ADMISSION_YEAR]; `source_url` non-empty.
  **Một entry lỗi → in toàn bộ lỗi, exit non-zero, không ghi gì.** Seed curated phải sạch 100% —
  lỗi resolve nghĩa là sửa dictionary `programs.json` hoặc sửa seed, không âm thầm bỏ qua.
- Ghi qua hàm mới `save_cutoff_records(records)` trong `ingestion/storage/db_writer.py`
  (upsert `ON CONFLICT ... DO UPDATE`, dùng `get_cursor` như các hàm hiện có).
- Dry-run: in bảng records đã normalize + đếm, không chạm DB.

#### 4.2.3 Parser proof-of-automation `hust_cutoff_html`

- `initial_sources.json` thêm source mới: `source_type: "cutoff_announcement"` (mở rộng Literal trong
  `ingestion/registry/models.py`), `parser_profile: "hust_cutoff_html"`, trust 5 — trang công bố
  điểm chuẩn 2025 trên `ts.hust.edu.vn`. **URL chính xác probe lúc implement** (pattern
  `scripts/hust_preflight_inspect.py`); fixture HTML tĩnh chụp về cho test.
- Parser deterministic theo template `hust_announcement_html_parser`: tìm bảng có header chứa
  "Điểm chuẩn"/"Điểm trúng tuyển", map cột mã ngành/tên ngành/điểm, trả `List[ExtractedCutoffFact]`,
  confidence 0.9. Đăng ký vào `ParserRegistry` như các parser hiện có.
- **Runner riêng** trong `ingest_cutoffs --source hust_cutoff_2025`: fetch (`http_fetcher`) → parser →
  normalize (resolve program/method bằng mapper hiện có, parse score) → `save_cutoff_records`.
  **Không đụng `IngestionPipeline`** — tránh trộn hai loại fact trong một pipeline.
- VNU-UET mọi năm + HUST 2023/2024 đi đường seed (không viết thêm parser ở phase này).

### WS3 — Retrieval attach lịch sử cutoff

`services/retrieval_service.py`:

- Hàm mới `fetch_cutoff_history(pairs: set[tuple[school_id, program_id]]) -> dict[tuple, list[CutoffEntry]]`
  — **một** query batch `SELECT ... FROM cutoff_records WHERE (school_id, program_id) IN (...)`,
  ORDER BY cutoff_year DESC, source_trust_level DESC.
- Gọi cuối `fetch_candidates()` (một điểm tích hợp duy nhất): attach `cutoff_history` cho từng
  candidate theo `(school_id, program_id)`; row cùng `candidate_id` (đa nguồn đề án) nhận history giống nhau.
- `program_id IS NULL` (candidate chưa resolve được chương trình) → không join, history rỗng.
- Query lỗi (bảng chưa migrate, DB lỗi) → `logger.warning` + history rỗng — **không bao giờ làm fail retrieval**.
- `services/mock_retrieval.py` không đổi → candidate mock không có history → toàn bộ hành vi cũ giữ nguyên.

### WS4 — Module đánh giá thuần `services/cutoff/assessment.py`

Nguồn sự thật duy nhất cho ngữ nghĩa cutoff; cả reasoning lẫn conflict_agent cùng gọi.

```python
def assess_cutoff(
    total_score: Optional[float],
    admission_method: Optional[str],
    cutoff_history: List[CutoffEntry],
) -> Optional[CutoffAssessment]
```

Hằng số (tập trung, docstring giải thích; doc edge-case không quy định số nên đây là tham số chỉnh được):

```python
BORDERLINE_MARGIN = 0.25      # EC-14: ví dụ doc +0.05 phải ra borderline ✓
SAFE_MARGIN = 1.0             # margin >= 1.0 mới được bonus tối đa
VOLATILITY_RANGE = 1.0        # EC-15: ví dụ doc range 1.9 phải ra volatile ✓
MIN_YEARS_VOLATILITY = 3      # < 3 năm dữ liệu thì không kết luận biến động
```

Logic:

1. **Gate**: `admission_method ∈ THANG_30_METHODS` và `total_score is not None` và history có entry
   `admission_method == profile method` với `score_scale == 30` (hoặc None coi như 30 — seed luôn ghi 30).
   Không thoả → trả `None` (reasoning giữ hành vi cũ).
2. **reference_year** = năm lớn nhất có entry sau filter. `entries_latest` = mọi entry của năm đó (đa nguồn).
3. **Phân loại per-value**: `margin = total_score - cutoff_score`:
   `margin < 0` → `below` · `0 <= margin < BORDERLINE_MARGIN` → `borderline` · còn lại → `above`.
4. **Conflict năm tham chiếu (EC-16)**: `values = distinct cutoff_score trong entries_latest`.
   `len(values) > 1` → `conflicted=True`, giữ `latest_values=[{value, source_url, trust_level}]`.
   Nhãn per-value khác nhau → `decision_changing=True`, nhãn cuối = **bảo thủ nhất**
   (thứ tự bảo thủ: `below` < `borderline` < `above` — lấy min). Nhãn giống nhau → nhãn chung.
5. **Biến động (EC-15)**: chuỗi 1 giá trị/năm — chọn entry trust cao nhất, tie-break
   `confidence_score` desc rồi `cutoff_score` desc (deterministic). Nếu số năm ≥ `MIN_YEARS_VOLATILITY`
   và `max - min >= VOLATILITY_RANGE` → `volatile=True`, **nhãn cuối = `uncertain`** (override),
   giữ `volatility_min/max` để giải thích.
6. `margin` trả về = margin so với giá trị trust cao nhất của năm tham chiếu.

```python
class CutoffAssessment(BaseModel):   # định nghĩa trong agents/models.py (xem 4.1.2)
    score_fit: Literal["above", "borderline", "below", "uncertain"]
    reference_year: int
    margin: float
    latest_values: List[Dict[str, Any]]   # [{value, source_url, trust_level}]
    conflicted: bool = False
    decision_changing: bool = False
    volatile: bool = False
    volatility_min: Optional[float] = None
    volatility_max: Optional[float] = None
    years_used: List[int] = Field(default_factory=list)
```

`assessment.py` chỉ chứa constants + `assess_cutoff` (+ helper classify cho conflict_agent).
Pure function — không I/O, không raise (input rác → `None`).

### WS5 — Reasoning + policy

`services/reasoning_service.py` (ngả 3 — đúng phương thức, sau check tổ hợp EC-12):

- Gọi `assess_cutoff(...)`. **Có assessment → thay hoàn toàn** bonus ngưỡng tuyệt đối (>=26/+0.10, >=24/+0.05)
  bằng bảng margin; **không có → giữ nguyên** nhánh cũ (defense khi chưa seed / mock retrieval):

| score_fit | Bonus | Band cap | Caution |
|---|---|---|---|
| `above`, margin ≥ 1.0 | +0.10 | — | — |
| `above`, margin < 1.0 | +0.05 | — | — |
| `borderline` | 0 | tối đa `match` | "Điểm sát ngưỡng tham chiếu {year} (+{margin}) — lựa chọn có rủi ro." |
| `below` | 0 | tối đa `reach` | "Điểm thấp hơn mức tham chiếu {year} ({margin})." |
| `uncertain` (volatile) | 0 | tối đa `match` | "Điểm chuẩn dao động {min}–{max} qua {n} năm gần nhất, chưa thể kết luận." |
| `decision_changing` (chồng lên nhãn) | 0 | tối đa `match` | dual-value note (WS7) |

- Band cap = `min(band, cap)` theo thứ tự `safe > match > reach` — đáp ứng "không hiển thị như lựa chọn an toàn".
  Nhiều cap cùng áp (vd `decision_changing` + nhãn `below`) → lấy **cap chặt nhất**.
- Khi `decision_changing`: caution của nhãn được **thay bằng dual-value note** (phát biểu một-nguồn
  kiểu "thấp hơn mức tham chiếu" gây hiểu lầm khi nguồn khác nói ngược lại).
- `decision_changing` → ngoài cap còn `candidate.data_uncertain_fields += "cutoff_score"`
  (cũng được conflict_agent mark — hai đường idempotent, dedupe khi append).
- Gắn `cutoff_assessment` vào `RankedRecommendation` tương ứng.

`services/policy_service.py`:

- Flag mới `historical_cutoff_reference` khi ≥1 recommendation có `cutoff_assessment`
  → explanation buộc render caveat toàn cục EC-18.
- Blocked claim mới `no_admission_assertion_on_reference_cutoff` khi ≥1 assessment có
  `score_fit ∈ {borderline, uncertain}` hoặc `decision_changing` — chặn ngôn ngữ khẳng định đỗ (EC-14 AC).

### WS6 — Conflict mở rộng

`services/conflict/detection.py`:

- `detect_cutoff_conflicts(candidates) -> List[ConflictRecord]`: dedupe candidate theo `candidate_id`
  (row đa nguồn đề án có history giống nhau), group entry theo `(school_id, program_id, cutoff_year, admission_method)`;
  group có ≥2 `cutoff_score` distinct → `ConflictRecord(field_name="cutoff_score")`, options từng nguồn
  (`EvidenceOption.value = cutoff_score`). **`ConflictRecord.admission_year` mang `cutoff_year`**
  (tái dùng field — ghi chú docstring rõ ràng).

`agents/conflict_agent.py` phân nhánh theo `field_name`:

- `quota` → `compare()` + `resolve()` (giữ nguyên, kể cả LLM tiebreaker).
- `cutoff_score` → **outcome deterministic, không LLM**: dùng helper classify của
  `services/cutoff/assessment.py` với `state.student_profile.total_score/admission_method`:
  - Hai giá trị cho hai nhãn khác nhau (decision-changing) → `status="unresolved"`,
    `uncertainty_reason` nêu cả hai giá trị + nguồn → `_mark_uncertain` (pattern sẵn có).
  - Cùng nhãn (hoặc thiếu profile score để phân loại) → `status="resolved"`,
    `resolved_value` = giá trị nguồn trust cao nhất, `rejected_evidence` giữ phần còn lại,
    `rationale` luôn nêu đủ các giá trị.

Lý do giữ conflict subsystem dù assessment đã biết `conflicted`: trace panel debug, policy flag
`retrieval_conflicts_detected`, và `_data_note` explanation đều ăn theo `ResolutionOutcome` — tái dùng nguyên wiring.

### WS7 — Explanation + fix EC-17

`services/explanation_service.py`:

- **Per-program** (recommendation có `cutoff_assessment`):
  - Dòng tham chiếu: `Điểm chuẩn tham chiếu {year}: {value} ({nhãn nguồn})`; khi `conflicted`:
    liệt kê đủ — `26.2 (trang trường) / 26.8 (cổng ĐHQG)` (`label_for_source` sẵn có) — EC-16 AC.
  - Nhãn score-fit: `above` → "Trên mức tham chiếu {year} (+{margin})" · `borderline` →
    "Sát ngưỡng tham chiếu {year} (+{margin}) — lựa chọn có rủi ro" · `below` →
    "Dưới mức tham chiếu {year}" · `uncertain` → "Điểm chuẩn dao động {min}–{max} qua {n} năm — chưa thể kết luận".
- **Caveat toàn cục (EC-18)** khi flag `historical_cutoff_reference`, khớp response mẫu doc:
  > "Chưa có điểm chuẩn chính thức cho kỳ tuyển sinh {admission_year}. Đánh giá dưới đây sử dụng
  > dữ liệu {years} làm tham chiếu và có thể thay đổi khi trường công bố thông tin mới."
- `_FIELD_LABELS += {"cutoff_score": "điểm chuẩn"}` → `_data_note` tự render đúng nhánh unresolved.
- **Fix EC-17**: `_data_note` nhánh resolved liệt kê đủ giá trị + nguồn từ `chosen_evidence` +
  `rejected_evidence` (dữ liệu đã có sẵn trên `ResolutionOutcome`, chỉ đổi render):
  > "Các nguồn ghi khác nhau về {field}: 120 ({nguồn A}) và 150 ({nguồn B}). Hệ thống tham chiếu 150 từ {nguồn B}, …"

Trace panel: không cần code mới — conflict stage đã serialize records/outcomes;
`cutoff_assessment` đi theo `model_dump()` của recommendation vào trace reasoning (verify khi implement).

## 5. Data flow sau thay đổi

```
seed JSON ──┐
            ├─ ingest_cutoffs (validate atomic → normalize → save_cutoff_records) ─→ cutoff_records
parser HTML ┘                                                                          │
                                                                                       ▼
advisory run: profile → retrieve (fetch_candidates + attach cutoff_history)
  → conflict (quota: compare/resolve như cũ · cutoff: deterministic, decision-changing → unresolved)
  → reason (assess_cutoff → bonus margin / band cap / cautions; fallback ngưỡng tuyệt đối khi không có data)
  → policy (+historical_cutoff_reference, +no_admission_assertion_on_reference_cutoff)
  → explain (nhãn score-fit + dòng tham chiếu + dual-source + caveat EC-18; _data_note đủ giá trị cho cả quota EC-17)
```

## 6. Error handling

- `fetch_cutoff_history` lỗi (chưa migrate, DB down) → `logger.warning` + history rỗng → assessment
  `None` → reasoning fallback ngưỡng tuyệt đối. **Không bao giờ chặn advisory.**
- Entry thang ≠ 30 / method ≠ profile → bị filter ở gate assessment. Không quy đổi thang trong mọi trường hợp.
- Helper classify trong conflict_agent thiếu `total_score` → coi như non-decision-changing →
  resolved theo trust (degrade, vẫn nêu đủ giá trị trong rationale).
- Seed loader: validate atomic, lỗi → exit non-zero không ghi gì. Parser lỗi → log + exit non-zero
  cho source đó, không ảnh hưởng dữ liệu seed đã có.
- `assess_cutoff` pure — không I/O; input rác trả `None`, không raise.

## 7. Testing (TDD per slice)

1. `tests/services/cutoff/test_assessment.py` (mới) — ma trận: EC-14 (26.25 vs 26.20 → `borderline`),
   EC-15 (24.8/26.7/25.9, điểm 26.4 → `uncertain`, range 1.9), EC-16 (26.2 vs 26.8, điểm 26.5 →
   `conflicted + decision_changing`, nhãn bảo thủ `below`… kiểm chứng: 26.5−26.8=−0.3 → below,
   26.5−26.2=+0.3 → above ⇒ final `below`), `above` margin lớn/nhỏ, gate trả `None`
   (sai method / thiếu điểm / history rỗng), 2 năm → không volatility, tie-break trust.
2. `tests/ingestion/test_cutoff_seed_loader.py` (mới) — validate atomic (1 entry hỏng → không ghi gì),
   resolve program qua dictionary, dry-run không chạm DB, upsert idempotent (fake cursor).
3. `tests/ingestion/test_hust_cutoff_html_parser.py` (mới) — fixture HTML tĩnh, đúng pattern parser test hiện có.
4. `tests/services/conflict/test_detection.py` (mở rộng) — group theo (school, program, year, method),
   dedupe candidate_id, 1 nguồn → không conflict.
5. `tests/agents/test_conflict_agent.py` (mở rộng) — cutoff decision-changing → unresolved + mark uncertain;
   non-decision-changing → resolved + rationale đủ giá trị; **không gọi LLM tiebreaker cho cutoff**
   (fake gateway phải không được invoke).
6. `tests/agents/test_reasoning_agent.py` (mở rộng) — có history: bonus margin thay bonus tuyệt đối,
   band cap đúng từng score_fit, caution đúng template; không history: test cũ giữ xanh nguyên trạng.
7. `tests/agents/test_policy_agent.py` (mở rộng) — 2 flag/claim mới đúng điều kiện kích hoạt.
8. `tests/agents/test_explanation_agent.py` (mở rộng) — dòng tham chiếu, dual display EC-16,
   `_data_note` đủ giá trị EC-17, caveat EC-18, nhãn EC-14/15.
9. `tests/integration/test_cutoff_records_e2e.py` (mới, Docker DB) — migration 016 + loader thật +
   `fetch_cutoff_history` join đúng.
10. `tests/e2e/test_advisory_flow.py` (mở rộng) — 4 kịch bản Given/When/Then của EC-14/15/16/18
    trong `docs/edge-case.md` làm acceptance test.

## 8. Tương thích ngược

- Mọi field mới Optional/default rỗng → fixture & test hiện có **không vỡ** (khác Phase 1 vốn cố ý vỡ fixture).
- `mock_retrieval` không có `cutoff_history` → assessment `None` → demo path cũ nguyên hành vi.
- Không sửa schema bảng hiện có; migration 016 thuần additive, idempotent.
- `result_json`/trace của run cũ không đổi schema (run mới có thêm field trong recommendation dump).

## 9. File inventory

| File | Thay đổi |
|---|---|
| `db/migrations/016_cutoff_records.sql` | MỚI — bảng + 2 index |
| `ingestion/models/pipeline_models.py` | += `ExtractedCutoffFact`, `NormalizedCutoffRecord` |
| `ingestion/cutoff/seeds/cutoff_2023_2025.json` | MỚI — seed curated kèm nguồn |
| `ingestion/ingest_cutoffs.py` (module CLI) | MỚI — validate atomic, dry-run, seed + source runner |
| `ingestion/storage/db_writer.py` | += `save_cutoff_records` |
| `ingestion/parsers/hust_cutoff_html_parser.py` | MỚI — parser deterministic |
| `ingestion/registry/models.py` | source_type += `cutoff_announcement` |
| `ingestion/registry/seeds/initial_sources.json` | += source điểm chuẩn HUST 2025 |
| `agents/models.py` | += `CutoffEntry`, `CutoffAssessment`; `CandidateProgram.cutoff_history`; `RankedRecommendation.cutoff_assessment` |
| `services/retrieval_service.py` | += `fetch_cutoff_history` + attach trong `fetch_candidates` |
| `services/cutoff/assessment.py` | MỚI — constants + `assess_cutoff` + helper classify |
| `services/reasoning_service.py` | bonus margin thay tuyệt đối khi có assessment, band cap, cautions |
| `services/policy_service.py` | += flag `historical_cutoff_reference`, claim `no_admission_assertion_on_reference_cutoff` |
| `services/conflict/detection.py` | += `detect_cutoff_conflicts` |
| `agents/conflict_agent.py` | phân nhánh quota/cutoff; outcome deterministic cho cutoff |
| `services/explanation_service.py` | nhãn score-fit, dòng tham chiếu, dual display, caveat EC-18, `_FIELD_LABELS`, fix `_data_note` EC-17 |
| `tests/...` | theo mục 7 |
