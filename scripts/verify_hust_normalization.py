"""
Assert that HUST program names (from BOTH sources) normalize to the same
program_id and admission_method. This is the key-alignment invariant that
makes rows from both sources land on the same canonical (program_id,
admission_method) pair in canonical_admission_records — needed even though
HUST 2026 is not expected to produce divergent quota values.

Pairs were generated from scripts/_probe_hust_pairs.py against:
  - hust_program_listing_2026
  - hust_announcement_html_2026
"""
import sys
sys.path.insert(0, ".")
from ingestion.normalization.program_mapper import map_program
from ingestion.normalization.method_mapper import map_method

# Pairs of (listing_name, announcement_name) for the same HUST program code.
# Format: (listing_name, announcement_name)
PROGRAM_PAIRS = [
    ("Kỹ thuật thực phẩm (Chương trình tiên tiến)", "Kỹ thuật Thực phẩm"),
    ("Kỹ thuật sinh học (Chương trình tiên tiến)", "Kỹ thuật sinh học"),
    ("Kỹ thuật Sinh học", "Kỹ thuật Sinh học"),
    ("Kỹ thuật Thực phẩm", "Kỹ thuật Thực phẩm"),
    ("Kỹ thuật Hóa dược (Chương trình tiên tiến)", "Kỹ thuật Hóa dược"),
    ("Kỹ thuật Hóa học", "Kỹ thuật Hóa học"),
    ("Hóa học", "Hóa học"),
    ("Công nghệ giáo dục", "Công nghệ Giáo dục"),
    ("Quản lý giáo dục", "Quản lý Giáo dục"),
    ("Tâm lý học công nghiệp và tổ chức", "Tâm lý học công nghiệp và tổ chức (mới)"),
    ("Hệ thống điện và năng lượng tái tạo (Chương trình tiên tiến)", "Hệ thống điện và năng lượng tái tạo"),
    ("Kỹ thuật Điều khiển - Tự động hóa (Chương trình tiên tiến)", "Kỹ thuật điều khiển-Tự động hóa"),
    ("Tin học công nghiệp và Tự động hóa (Chương trình Việt-Pháp PFIEV)", "Tin học công nghiệp và Tự động hóa"),
    ("Kỹ thuật điện", "Kỹ thuật điện"),
    ("Kỹ thuật Điều khiển - Tự động hóa", "Kỹ thuật điều khiển & Tự động hóa"),
    ("Phân tích kinh doanh (Chương trình tiên tiến)", "Phân tích Kinh doanh"),
    ("Logistics và Quản lý chuỗi cung ứng (Chương trình tiên tiến)", "Logistics và Quản lý chuỗi cung ứng"),
    ("Kế toán (Chương trình tiên tiến)", "Kế toán (mới)"),
    ("Quản lý năng lượng", "Quản lý Năng lượng"),
    ("Quản lý công nghiệp", "Quản lý Công nghiệp"),
    ("Quản trị kinh doanh", "Quản trị Kinh doanh"),
    ("Tài chính - Ngân hàng", "Tài chính-Ngân hàng"),
    ("Truyền thông số và Kỹ thuật đa phương tiện (Chương trình tiên tiến)", "Truyền thông số và Kỹ thuật đa phương tiện"),
    ("Kỹ thuật Điện tử - Viễn thông (Chương trình tiên tiến)", "Kỹ thuật Điện tử - Viễn thông"),
    ("Kỹ thuật Y sinh (Chương trình tiên tiến)", "Kỹ thuật Y sinh"),
    ("Hệ thống nhúng thông minh và IoT (Chương trình tiên tiến)", "Hệ thống nhúng thông minh và IoT (tăng cường tiếng Nhật)"),
    ("Điện tử-Viễn thông - ĐH Leibniz Hannover (Đức)", "Điện tử - Viễn thông - ĐH Leibniz Hannover (CHLB Đức)"),
    ("Điện tử và Viễn thông", "Kỹ thuật Điện tử-Viễn thông"),
    ("Kỹ thuật Y sinh", "Kỹ thuật Y sinh"),
    ("Kỹ thuật Môi trường", "Kỹ thuật Môi trường"),
    ("Quản lý Tài nguyên và Môi trường", "Quản lý Tài nguyên và Môi trường"),
    ("Tiếng Anh Khoa học Kỹ thuật và Công nghệ", "Tiếng Anh KHKT và Công nghệ"),
    ("Tiếng Anh Chuyên nghiệp Quốc tế", "Tiếng Anh chuyên nghiệp quốc tế (do ĐHBK Hà Nội và ĐH Plymouth Marjon - Vương quốc Anh cấp bằng)"),
    ("Tiếng Trung Khoa học và Công nghệ", "Tiếng Trung KH & CN"),
    ("Tiếng Hàn Khoa học và Công nghệ", "Tiếng Hàn KH&CN (mới)"),
    ("Kỹ thuật Nhiệt", "Kỹ thuật Nhiệt"),
    ("Khoa học Dữ liệu và Trí tuệ Nhân tạo", "Khoa học Dữ liệu và Trí tuệ nhân tạo"),
    ("An toàn không gian số (Chương trình tiên tiến)", "An toàn không gian số - Cyber Security"),
    ("Công nghệ thông tin (Việt-Nhật) (Chương trình tiên tiến)", "Công nghệ Thông tin Việt - Nhật (tăng cường tiếng Nhật)"),
    ("Công nghệ thông tin (Global ICT)", "Công nghệ Thông tin Global ICT"),
    ("Công nghệ thông tin (Việt-Pháp) (Chương trình tiên tiến)", "Công nghệ Thông tin Việt - Pháp (tăng cường tiếng Pháp)"),
    ("CNTT: Khoa học Máy tính", "CNTT: Khoa học Máy tính"),
    ("CNTT: Kỹ thuật máy tính", "CNTT: Kỹ thuật Máy tính"),
    ("Kỹ thuật Cơ điện tử (Chương trình tiên tiến)", "Kỹ thuật Cơ điện tử"),
    ("Cơ khí - Chế tạo máy - ĐH Griffith (Úc)", "Cơ khí Chế tạo máy - hợp tác với trường ĐH Griffith (Úc)"),
    ("Cơ điện tử - ĐH Leibniz Hannover (Đức)", "Cơ điện tử - hợp tác với ĐH Leibniz Hannover (CHLB Đức)"),
    ("Cơ điện tử - ĐH Nagaoka (Nhật Bản)", "Cơ điện tử - hợp tác với ĐHCN Nagaoka (Nhật Bản)"),
    ("Kỹ thuật Cơ điện tử", "Kỹ thuật Cơ điện tử"),
    ("Kỹ thuật Cơ khí", "Kỹ thuật Cơ khí"),
    ("Toán - Tin", "Toán-Tin"),
    ("Hệ thống thông tin quản lý", "Hệ thống Thông tin quản lý"),
    ("Khoa học và Kỹ thuật Vật liệu (Chương trình tiên tiến)", "Khoa học và Kỹ thuật Vật liệu"),
    ("Kỹ thuật Vật liệu", "Kỹ thuật Vật liệu"),
    ("Chương trình Kỹ thuật vi điện tử và công nghệ Nano", "Kỹ thuật Vi điện tử và Công nghệ nano"),
    ("Công nghệ vật liệu polyme và compozit", "Công nghệ vật liệu Polyme và Compozit"),
    ("Kỹ thuật in", "Kỹ thuật In"),
    ("Vật lý kỹ thuật", "Vật lý Kỹ thuật"),
    ("Kỹ thuật hạt nhân", "Kỹ thuật Hạt nhân"),
    ("Vật lý Y khoa", "Vật lý Y khoa"),
    ("Kỹ thuật Ô tô (Chương trình tiên tiến)", "Kỹ thuật Ô tô"),
    ("Cơ khí hàng không (Chương trình Việt - Pháp PFIEV)", "Cơ khí Hàng không"),
    ("Kỹ thuật Ô tô", "Kỹ thuật Ô tô"),
    ("Kỹ thuật Cơ khí động lực", "Kỹ thuật Cơ khí động lực"),
    ("Kỹ thuật Hàng không", "Kỹ thuật Hàng không"),
    ("Khoa học máy tính - ĐH Troy (Hoa Kỳ)", "Khoa học Máy tính - ĐH Troy (Hoa Kỳ) (do ĐH Troy cấp bằng)"),
    ("Công nghệ Dệt May", "Công nghệ Dệt May"),
]

# Methods that both sources are expected to emit. The canonical codes are
# keys in methods.json.
KNOWN_METHOD_CODES = {
    "thpt_score", "school_record", "talent_admission",
    "combined", "competency_test",
}

METHOD_SAMPLES = [
    "Xét tuyển tài năng",
    "xét tuyển tài năng",
    "xét tuyển tài năng 2023",
    "Xét tuyển bằng Giải thưởng HSG QG-QT/Chứng chỉ Quốc tế/HSNL",
    "Xét tuyển theo KQ Kỳ thi ĐGTD",
    "xét tuyển theo KQ Kỳ thi ĐGTD",
    "Xét tuyển theo KQ Kỳ thi TN THPT",
    "xét tuyển theo KQ Kỳ thi TN THPT",
    "Xét tuyển dựa trên kết quả thi tốt nghiệp THPT",
    "Xét tuyển dựa trên Kỳ thi đánh giá tư duy",
    "Xét tuyển dựa trên kết quả Kỳ thi đánh giá tư duy",
    "Xét tuyển dựa trên kết quả Kỳ thi Đánh giá tư duy",
    "Xét tuyển dựa trên kết quả bài kiểm tra tư duy",
    "Xét tuyển thẳng (Xét tuyển tài năng)",
    "Xét tuyển thẳng (xét tuyển tài năng)",
    "Xét tuyển tài năng (Xét tuyển thẳng)",
    "Xét tuyển tài năng (Xét tuyển thẳng )",
]

all_ok = True

print("=== Program mapping (cross-source invariant) ===")
mismatch_count = 0
null_count = 0
for listing_name, announcement_name in PROGRAM_PAIRS:
    pid_listing, canon_listing = map_program(listing_name, school_id="hust")
    pid_announcement, canon_announcement = map_program(announcement_name, school_id="hust")
    match = pid_listing and pid_listing == pid_announcement
    status = "MATCH" if match else "MISMATCH"
    if not match:
        all_ok = False
        mismatch_count += 1
    if pid_listing is None or pid_announcement is None:
        null_count += 1
        all_ok = False
    print(f"  [{status}]")
    print(f"    listing      : {listing_name!r} -> pid={pid_listing!r}  canon={canon_listing!r}")
    print(f"    announcement : {announcement_name!r} -> pid={pid_announcement!r}  canon={canon_announcement!r}")

print(f"\n  Total pairs: {len(PROGRAM_PAIRS)}  Mismatches: {mismatch_count}  Null pids: {null_count}")

print("\n=== Method mapping ===")
method_fail = 0
for raw in METHOD_SAMPLES:
    result = map_method(raw, school_id="hust")
    parts = [p.strip() for p in (result or "").split(";")]
    mapped = bool(parts) and all(p in KNOWN_METHOD_CODES for p in parts if p)
    status = "OK" if mapped else "UNMAPPED"
    if not mapped:
        all_ok = False
        method_fail += 1
    print(f"  [{status}] {raw!r} -> {result!r}")

print(f"\n  Total methods: {len(METHOD_SAMPLES)}  Failures: {method_fail}")

if all_ok:
    print("\nPASS")
else:
    print("\nFAIL — fix the dictionaries above and re-run")
    sys.exit(1)
