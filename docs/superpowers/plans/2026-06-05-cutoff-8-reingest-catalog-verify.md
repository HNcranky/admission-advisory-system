# Cutoff Plan 8 — Re-ingest canonical hust + rebuild catalog + verify end-to-end

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Canonical store hust sạch (variant Troy/Việt-Nhật/CT tiên tiến về id riêng, hết đè IT1), major catalog nhận ngành mới, advisory end-to-end đúng với dictionary mở rộng.

**Architecture:** Xoá canonical hust rồi re-ingest qua `ingestion.main --school hust` (upsert key `(school, year, program_id, method, source_url)` — xoá trước để loại row mồ côi mang id sai từ thời fuzzy). Rebuild pgvector catalog bằng `services/profile/build_major_catalog` (nguồn = DISTINCT program_id của canonical store). Toàn bộ là thao tác dữ liệu + verify — KHÔNG sửa code; nếu verify lộ bug code → DỪNG, báo lại, không vá tại chỗ. Spec: `docs/superpowers/specs/2026-06-05-cutoff-tsn247-api-dictionary-design.md`.

**Tech Stack:** Docker Postgres (pgvector), psql, uvicorn smoke.

**Phụ thuộc:** Plan 6 (dictionary). Khuyến nghị sau Plan 7 để smoke thấy đủ 4 năm cutoff. Cần `.env` (GEMINI key cho embed catalog) + DB up.

**Lưu ý nghiệp vụ đã biết trước:**
- Trước plan 6, fuzzy map gán "Khoa học máy tính - hợp tác ĐH Troy" → `computer_science`
  (đè IT1 thật trong canonical 2026 — thấy ở smoke plan 5); "Hệ thống nhúng IoT" →
  `printing_technology`; "Polyme và Compozit" → `mechanical_engineering`…
- `ingestion.main --school hust` fetch mạng (ts.hust.edu.vn) — chạy được như plan 5 đã làm.
- Catalog build embed bằng Gemini — chỉ embed entry đổi content_hash (idempotent, rẻ).

---

### Task 1: Re-ingest canonical hust

- [ ] **Step 1: Snapshot trạng thái TRƯỚC** (để đối chiếu):

```bash
docker start advisory-db 2>/dev/null; set -a; source .env; set +a
docker exec advisory-db psql -U postgres -d admission -c "
SELECT count(*) AS total, count(DISTINCT program_id) AS ids
FROM canonical_admission_records WHERE school_id='hust';"
docker exec advisory-db psql -U postgres -d admission -c "
SELECT program_id, program_name_raw FROM canonical_admission_records
WHERE school_id='hust' AND (program_name_raw ILIKE '%troy%'
   OR program_name_raw ILIKE '%việt - nhật%' OR program_name_raw ILIKE '%global ict%')
ORDER BY 1;" | tee /tmp/canonical_hust_before.txt
```

Expected (trước fix): các row Troy/Việt-Nhật/Global ICT mang `program_id` ngành gốc
(`computer_science`...).

- [ ] **Step 2: Xoá canonical hust** (loại row mồ côi id sai — upsert không tự dọn):

```bash
docker exec advisory-db psql -U postgres -d admission -c "
DELETE FROM canonical_admission_records WHERE school_id='hust';"
```

- [ ] **Step 3: Re-ingest**

Run: `python -m ingestion.main --school hust`
Expected: pipeline chạy hết, lưu ~130+ records (trước: 112 — variant hết đè nhau nên TĂNG).

- [ ] **Step 4: Verify SAU**

```bash
docker exec advisory-db psql -U postgres -d admission -c "
SELECT count(*) AS total, count(DISTINCT program_id) AS ids
FROM canonical_admission_records WHERE school_id='hust';"
docker exec advisory-db psql -U postgres -d admission -c "
SELECT program_id, program_name_raw FROM canonical_admission_records
WHERE school_id='hust' AND (program_name_raw ILIKE '%troy%'
   OR program_name_raw ILIKE '%việt - nhật%' OR program_name_raw ILIKE '%global ict%')
ORDER BY 1;"
docker exec advisory-db psql -U postgres -d admission -c "
SELECT DISTINCT program_name_raw FROM canonical_admission_records
WHERE school_id='hust' AND program_id='computer_science';"
```

Expected:
- total ≥ trước, ids tăng rõ (~50+ id thay vì ~38);
- row Troy → `computer_science_troy` / `business_administration_troy`; Việt-Nhật →
  `information_technology_viet_nhat`; Global ICT → `information_technology_global_ict`;
- `computer_science` CHỈ còn raw name "CNTT: Khoa học Máy tính" (± biến thể IT1 chính chủ).
  Nếu còn raw name lạ → dictionary thiếu alias: DỪNG, báo lại (bổ sung alias là việc plan 6).

---

### Task 2: Rebuild major catalog (pgvector)

- [ ] **Step 1: Build**

Run: `python -m services.profile.build_major_catalog`
Expected: `program catalog: total=<~70+> embedded=<số entry mới/đổi> reused=<phần còn lại>` —
embedded > 0 (có ngành mới).

- [ ] **Step 2: Verify nhanh**

```bash
docker exec advisory-db psql -U postgres -d admission -c "
SELECT program_id FROM program_catalog_embeddings
WHERE program_id IN ('computer_science_troy','information_technology_viet_nhat',
                     'vehicle_engineering','chemistry') ORDER BY 1;"
```

Expected: đủ 4 row.

---

### Task 3: Verify end-to-end

- [ ] **Step 1: Toàn suite**

Run: `python -m pytest -q` → toàn xanh; `python -m pytest tests/integration tests/e2e -q` → xanh.

- [ ] **Step 2: Smoke UI** — `python -m uvicorn --factory web.app:build_app --port 8765`
(LƯU Ý: app dùng factory — `web.app:app` trong CLAUDE.md đã cũ). Kịch bản KHMT lặp lại từ
smoke plan 5: "Em được 29.1 điểm thi THPT khối A00 năm 2026, muốn vào ngành Khoa học máy tính
của Bách khoa Hà Nội" qua `POST /api/sessions` + `POST .../messages` + poll.

Expected:
- Candidate #1 là **"Khoa học Máy tính"** (computer_science) với cutoff tham chiếu 29.19 —
  KHÔNG còn hiện "Khoa học Máy tính - ĐH Troy" như trước plan 6;
- Caveat năm tham chiếu vẫn hiện; 2 nguồn cutoff (seed + tsn247) vẫn cạnh nhau.

- [ ] **Step 3: Smoke variant** — kịch bản mới: "Em 24 điểm khối A00 năm 2026, em quan tâm
chương trình Khoa học máy tính hợp tác ĐH Troy của Bách khoa". Expected: candidate
`computer_science_troy` xuất hiện với cutoff lịch sử riêng (2022: 21.3–25.15 tuỳ năm có dữ
liệu plan 7), nhãn đánh giá hợp lý, không lẫn điểm 29.x của IT1.

- [ ] **Step 4: Dừng uvicorn** sau smoke.

---

### Task 4: Khép phase

- [ ] **Step 1:** Tick checkbox 3 plan 6/7/8 + cập nhật bảng index
`2026-06-05-cutoff-0-index.md` (3 dòng mới → xong).
- [ ] **Step 2:** Cập nhật memory `edge-case-conformance`: dictionary BKA 65 mã, đường API
tsn247 2022–2025, canonical hust sạch variant — kèm gotcha "mã đổi số giữa các năm, codes map
= mã 2025".
- [ ] **Step 3:** Commit docs/memory. Giữ branch như user chỉ định.
