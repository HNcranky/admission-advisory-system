# Design: Phủ đủ ngành BKA + đường API điểm chuẩn tuyensinh247 (2022–2025)

**Ngày:** 2026-06-05 · **Trạng thái:** đã duyệt với user (chat) · **Tiếp nối:** cutoff plan 5
(`2026-06-05-cutoff-5-hust-parser.md`) · **Tham chiếu:** `docs/crawl_cutoff_score.md`

## Mục tiêu

1. `programs.json` phủ **đủ 65 mã tuyển sinh BKA** (hiện ~30) — mỗi mã một `program_id` riêng,
   variant (CT tiên tiến / hợp tác quốc tế) KHÔNG gộp vào ngành gốc.
2. Parser **API JSON** của diemthi.tuyensinh247.com lấy đủ điểm chuẩn **2022–2025 × 4 phương thức**
   (~756 facts → ~690 record trust 3 sau dedup 2025 THPT) nằm cạnh seed chính thức trust 5.
3. Re-ingest canonical store hust → fix root cause variant Troy/Việt-Nhật bị fuzzy gán nhầm
   vào ngành gốc và đè record thật (phát hiện ở smoke plan 5).

## Quyết định đã chốt với user

- **Đường API thay vì Playwright** — `docs/crawl_cutoff_score.md` đề xuất 2 nhánh (browser
  automation click "Xem thêm" / "inspect API mà trang gọi ngầm"); chọn nhánh API: không thêm
  dependency browser, JSON có sẵn `code` (mã tuyển sinh — DOM không có) + `block` (tổ hợp),
  fixture-testable. Nguyên tắc "lưu raw trước, normalize sau" của doc đã sẵn trong pipeline
  (`ExtractedCutoffFact` → `NormalizedCutoffRecord`).
- **Mapping theo MÃ tuyển sinh** (ưu tiên cao nhất, trước exact name).
- **id scheme:** tiếng Anh mô tả + suffix variant (khớp convention `_uet` sẵn có).
- **Re-ingest canonical hust** trong cùng đợt + rebuild major catalog (pgvector).
- **Mở rộng dictionary đủ 65 mã** (user yêu cầu full coverage BKA).

## API (đã verify 2026-06-05)

```
GET https://diemthi.tuyensinh247.com/api/common/cutoff-score?school_id=302&method_id={m}&year={y}
→ {"success": true, "data": [{"code": "IT1", "name": "CNTT: Khoa học Máy tính",
   "block": "A00;A01", "mark": 29.42, "year": 2023, "admission_name": "Điểm thi THPT", ...}]}
```

- `school_id=302` = BKA (lấy từ flight payload trang); method: 1=THPT, 6=ĐGTD, 10=XTKH, 12=CCQT
  (bảng `allMethods` trong JS bundle của trang).
- Coverage: 2022 (THPT 55, ĐGTD 60), 2023 (63/61), 2024 (64/64/64), 2025 (130*/65/65/65).
  (*) 2025 THPT mỗi ngành 2 row theo nhóm tổ hợp — dedup giữ-row-đầu sẵn có xử lý.
- **Quirk 2022:** mã có hậu tố `y` (`IT2y`, `TROY-ITy`) — parser strip một hậu tố `y`/`Y`
  khi mã gốc (sau strip) tồn tại; coverage 2022 một phần là chấp nhận được.
- API không phải public contract → fixture snapshot + source `active:false`; đổi schema thì
  runner exit 1 rõ ràng, không hỏng đường seed.
- Cross-check đã làm: IT1/IT-E10/IT-E15/MI1 2023–2024 khớp 100% seed + QĐ chính thức HUST.

## Thành phần

### 1. `programs.json` — section `hust`

Field mới **`"codes": ["IT1"]`** trên mỗi entry hust (mapper đọc; entry không có codes giữ
nguyên hành vi). Alias entry mới = **chỉ các biến thể tên đầy đủ** giữa các năm (hoa/thường,
"hoá/hóa", có/không khoảng trắng quanh "-") — KHÔNG alias ngắn, vì `load_program_aliases()`
flatten mọi scope vào profile extraction (match alias trên text chat của học sinh).

**30 mã đã resolve** (chỉ thêm `codes`): BF1 bioengineering, BF2 food_technology,
ED2 education_technology, ED3 education_management, EE1 electrical_engineering,
EM1 energy_management, EM2 industrial_management, EM3 business_administration, EM4 accounting,
EM5 finance_banking, ET1 electronics_telecom, ET2 biomedical_engineering,
EV1 environmental_engineering, FL1 english_science_tech, FL2 english_professional,
HE1 heat_engineering, IT-E10 data_science, IT-E15 cyber_security, IT1 computer_science,
ME1 mechatronics, ME2 mechanical_engineering, MI1 math_informatics, MS1 materials_science,
MS2 microelectronics_nano, MS5 printing_technology, PH1 physics, PH2 nuclear_engineering,
PH3 medical_physics, TE1 automotive_engineering, TE3 aerospace_engineering.

**8 mã reuse id sẵn có** (thêm alias + codes, id đã tồn tại trong `_shared`/`hust`):

| Mã | Tên trên API | id reuse | Ghi chú |
|---|---|---|---|
| CH1 | Kỹ thuật Hoá học | `chemical_engineering` | lệch "Hoá/Hóa" |
| EE2 | Kỹ thuật Điều khiển - Tự động hoá | `control_automation` | lệch "hoá/hóa" |
| CH-E11 | Kỹ thuật Hóa dược (CT tiên tiến) | `pharmaceutical_chemistry` | mã duy nhất của ngành |
| EE-E18 | Hệ thống điện và NL tái tạo (CT tiên tiến) | `power_renewable_energy` | mã duy nhất |
| EM-E14 | Logistics và QL chuỗi cung ứng (CT tiên tiến) | `logistics` | mã duy nhất |
| ET-E9 | Hệ thống nhúng thông minh và IoT (CT tiên tiến) | `embedded_systems` | mã duy nhất |
| FL3 | Tiếng Trung KHKT và Công nghệ | `chinese_science_tech` | |
| TX1 | Công nghệ Dệt - May | `textile_technology` | |

**27 entry MỚI:**

| Mã | Tên trên API | program_id mới |
|---|---|---|
| BF-E12 | Kỹ thuật Thực phẩm (CT tiên tiến) | `food_technology_advanced` |
| BF-E19 | Kỹ thuật sinh học (CT tiên tiến) | `bioengineering_advanced` |
| CH2 | Hoá học | `chemistry` |
| EE-E8 | Kỹ thuật Điều khiển - Tự động hoá (CT tiên tiến) | `control_automation_advanced` |
| EE-EP | Tin học công nghiệp và Tự động hóa (Việt - Pháp PFIEV) | `industrial_informatics_pfiev` |
| EM-E13 | Phân tích kinh doanh (CT tiên tiến) | `business_analytics` |
| ET-E16 | Truyền thông số và KT đa phương tiện (CT tiên tiến) | `digital_media_engineering` |
| ET-E4 | Kỹ thuật Điện tử - Viễn thông (CT tiên tiến) | `electronics_telecom_advanced` |
| ET-E5 | Kỹ thuật Y sinh (CT tiên tiến) | `biomedical_engineering_advanced` |
| ET-LUH | Điện tử - Viễn thông - hợp tác ĐH Leibniz Hannover | `electronics_telecom_leibniz` |
| EV2 | Quản lý Tài nguyên và Môi trường | `resource_environment_management` |
| IT-E6 | Công nghệ thông tin (Việt - Nhật) | `information_technology_viet_nhat` |
| IT-E7 | Công nghệ thông tin (Global ICT) | `information_technology_global_ict` |
| IT-EP | Công nghệ thông tin (Việt - Pháp) | `information_technology_viet_phap` |
| IT2 | CNTT: Kỹ thuật Máy tính | `computer_engineering` (scope hust; id trùng nghĩa với uet scope là chấp nhận được) |
| ME-E1 | Kỹ thuật Cơ điện tử (CT tiên tiến) | `mechatronics_advanced` |
| ME-GU | Cơ khí - Chế tạo máy - hợp tác ĐH Griffith (Úc) | `mechanical_engineering_griffith` |
| ME-LUH | Cơ điện tử - hợp tác ĐH Leibniz Hannover (Đức) | `mechatronics_leibniz` |
| ME-NUT | Cơ điện tử - hợp tác ĐH CN Nagaoka (Nhật Bản) | `mechatronics_nagaoka` |
| MI2 | Hệ thống thông tin quản lý | `management_information_systems` |
| MS-E3 | Khoa học và kỹ thuật vật liệu (CT tiên tiến) | `materials_science_advanced` |
| MS3 | Công nghệ vật liệu Polyme và Compozit | `polymer_composite_materials` |
| TE-E2 | Kỹ thuật Ô tô (CT tiên tiến) | `automotive_engineering_advanced` |
| TE-EP | Cơ khí hàng không (Việt - Pháp PFIEV) | `aerospace_mechanics_pfiev` |
| TE2 | Kỹ thuật Cơ khí động lực | `vehicle_engineering` |
| TROY-BA | Quản trị kinh doanh - hợp tác ĐH Troy (Hoa Kỳ) | `business_administration_troy` |
| TROY-IT | Khoa học máy tính - hợp tác ĐH Troy (Hoa Kỳ) | `computer_science_troy` |

Lưu ý MS-E3 vs MS1: canonical `materials_science` = "Khoa học và Kỹ thuật Vật liệu" khớp tên
MS-E3 hơn, nhưng MS1 đang resolve vào đó từ trước — giữ MS1 = `materials_science`,
MS-E3 = `materials_science_advanced` (exact alias đầy đủ tách 2 mã sạch).

### 2. `map_program` — stage 0 match theo mã

```python
map_program(name, code, school_id, exact_only=False)
# stage 0 (MỚI): code và school_id có giá trị → tra codes[] của school scope
#   (case-insensitive). Hit → return (program_id, canonical_name) ngay.
#   (Quirk hậu tố 'y' 2022 xử lý ở PARSER — site-specific; mapper giữ generic.)
# stage 1: exact name/alias (giữ nguyên)
# stage 2/3: substring/fuzzy — exact_only=True chặn (giữ nguyên)
```

Lookup codes build từ school scope (KHÔNG _shared — mã tuyển sinh là per-trường). Caller
không truyền code → hành vi y nguyên (backward compatible).

### 3. Parser `tuyensinh247_cutoff_api` — file mới `ingestion/parsers/tuyensinh247_cutoff_api_parser.py`

- Chữ ký `parse(content, source_url, cutoff_year=None, school_id="hust", school_name=...,
  trust_level=3)` — y hệt parser HTML; đăng ký thêm vào `CUTOFF_PARSERS`.
- `json.loads(content)`; `success != true` hoặc thiếu `data` → `[]` + `logger.warning`.
- Mỗi row → `ExtractedCutoffFact`: `program_code` (strip hậu tố y), `program_name=name`,
  `subject_combinations_raw = block.split(";")` (rỗng → None), `cutoff_score_raw=str(mark)`,
  `admission_method_raw=admission_name`, `cutoff_year=row["year"]` (tin row, không tin URL);
  row thiếu `mark`/`name` → bỏ + debug log. `cutoff_year` param = filter như parser HTML.
- `confidence_score=0.85`, `extraction_method="tuyensinh247_cutoff_api"`,
  `source_id=f"tsn247_api_{school_id}_{year}"`.

### 4. Runner & backfill — KHÔNG sửa runner

URL API đi qua `--source-url` + `--parser tuyensinh247_cutoff_api` sẵn có. Backfill = vòng
lặp bash 11 tổ hợp có dữ liệu (2022×2, 2023×2, 2024×3, 2025×4). `_SCORE_RE` của normalize chấp nhận mark số
(`"29.42"`); thang điểm theo method giữ nguyên (THPT 30, còn lại 100).
Bookkeeping: thêm entry `hust_cutoff_tsn247_api` vào `initial_sources.json`
(`source_type: cutoff_announcement`, `active: false`, trust 3, root_url = API base).

### 5. Re-ingest canonical hust + catalog

1. `python -m ingestion.main --school hust` sau khi dictionary mở rộng — exact stage bắt
   variant trước substring → Troy/Việt-Nhật/CT tiên tiến về id riêng, IT1 thật giữ
   `computer_science`.
2. Verify trước/sau: đếm record theo program_id, soi nhóm IT (computer_science chỉ còn row
   "CNTT: Khoa học Máy tính"), smoke EC-16 KHMT phải hiện đúng tên ngành gốc.
3. Rebuild major catalog (`build_major_catalog`) để hội thoại nhận diện ngành mới.

### 6. Dọn dữ liệu cũ sai

Canonical store hiện có row variant mang id ngành gốc (Troy đè IT1). Sau re-ingest, row đúng
ghi đè theo unique key. Kiểm tra row mồ côi (program_id cũ sai không còn được ghi lại) và xóa
nếu có — qua so sánh count/id trước-sau.

## Testing

- TDD từng mảnh: stage-0 mapper (hit theo code, quirk y, không ảnh hưởng khi code=None);
  parser API (synthetic JSON + fixture snapshot thật 1 năm×1 method); dictionary integrity
  (65/65 mã resolve qua `map_program(code=...)`, không mã trùng giữa các entry, mọi entry có
  canonical_name); normalize tích hợp (facts API → records, method scale đúng).
- Toàn suite + integration/e2e Docker DB; smoke web UI EC-14/15/16 sau re-ingest.
- Test guard profile: alias mới không làm `extract_major_mentions` bắt nhầm câu chat phổ biến
  ("em muốn học công nghệ thông tin" KHÔNG ra variant Việt-Nhật).

## Rủi ro & chấp nhận

- API tsn247 có thể đổi/chặn — fixture + active:false + exit code rõ; đường seed không phụ thuộc.
- Điểm 2022–2024 aggregator chưa cross-check từng số với nguồn chính thức (trừ nhóm demo đã
  khớp 100%) — trust 3 phản ánh đúng; conflict detector EC-16 sẽ lộ lệch nếu có seed đối chứng.
- 2022 coverage một phần (55/65) — chấp nhận, ghi log SKIP.
- Thêm ~27 program_id mới làm danh sách ngành advisory dài ra — đúng chủ đích (user muốn full
  coverage); nhãn variant rõ ràng trong canonical_name để học sinh phân biệt.
