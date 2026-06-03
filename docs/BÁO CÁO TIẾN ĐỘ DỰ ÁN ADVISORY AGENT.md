BÁO CÁO TIẾN ĐỘ DỰ ÁN ADVISORY AGENT

1\. Những gì đã hoàn thành  
1.1. Ingestion Pipeline  
Hạ tầng pipeline đa tầng:

* Source Registry — Quản lý danh sách nguồn dữ liệu. Hiện có 8 nguồn từ Đại học Bách khoa Hà Nội (HUST), bao gồm trang ngành đào tạo, đề án tuyển sinh, điểm chuẩn, học phí. Hỗ trợ trust level, priority, fetch strategy.

* Fetchers — HTTP fetcher với user-agent rotation. Có fetch dispatcher chọn strategy phù hợp (http/browser/api).	

* Document Router — Phân loại tài liệu tự động theo 3 bước: Content-Type header → URL pattern → magic bytes. Hỗ trợ HTML, PDF (text/scanned), DOCX, image, Facebook post.

* Parsers — 3 parser: HTML (trích xuất text, tables, links, headings), PDF (pdfminer, phân biệt text-based vs scanned), HUST program parser (chuyên biệt cho trang ngành Bách Khoa). Có parser dispatcher chọn parser theo document type và parser profile.

* Extractors — 2 phương thức trích xuất:  
  * Regex-based: trích xuất admission facts bằng pattern matching  
  * LLM-based: dùng Gemini 2.5 Flash với structured output prompt (chưa tích hợp)  
* Normalization — Chuẩn hóa dữ liệu thô thành format canonical:  
  * Method mapper: map phương thức tuyển sinh (xét tuyển thẳng, điểm THPT, đánh giá tư duy...)  
  * Program mapper: map tên ngành về tên chuẩn  
  * Subject combination mapper: map tổ hợp môn (A00, D01...)  
  * Quota parser: parse chỉ tiêu (số cụ thể, khoảng, xấp xỉ)  
  * 3 bộ từ điển JSON (methods, programs, subjects)

* CLI — Entry point python \-m ingestion.main với các chế độ: chạy cho 1 URL, 1 source, 1 trường, hoặc mặc định HUST.

1.2. Database  
PostgreSQL schema gồm 5 bảng, đã có migration scripts:

* source\_registry — Lưu nguồn dữ liệu (trust level, fetch strategy, parser profile).  
* discovered\_resources — Lưu URL đã phát hiện, trạng thái xử lý.  
* raw\_documents — Lưu nội dung thô (raw HTML/PDF dạng BYTEA, headers, content hash).  
* extracted\_facts — Lưu dữ kiện trích xuất trước normalization (school, program, method, quota, deadline).  
* canonical\_admission\_records — Bản ghi cuối cùng đã chuẩn hóa, dùng UPSERT trên composite key (school\_id, admission\_year, program\_id, admission\_method).

Các scripts hỗ trợ:

* setup\_db.py — Tạo database, chạy migrations, verify tables, seed source registry (1 lệnh chạy tất cả).  
* db\_writer.py (trong storage/) — 3 hàm write: save\_raw\_document(), save\_extracted\_facts(), save\_canonical\_records().  
* db\_connection.py — Context manager get\_cursor() cho database operations.  
* reimport.py, verify\_db.py, clean\_and\_verify.py — Tiện ích import lại, kiểm tra, dọn dẹp.

1.3. Dữ liệu đã thu thập  
Đã crawl 1 trường: HUST (Đại học Bách khoa Hà Nội)

* 281 records thô từ pipeline output (lưu trong 3 file JSON, tổng \~50K dòng)  
* 103 records đã clean và import vào database  
* 86 ngành unique

2\. Khó khăn

* Hiện tại luồng ingestion\_pipeline vẫn đang dùng hardcode cho các website của Bách Khoa, chưa tổng quát hóa cho nhiều trường đại học  
* Vì extract method còn đang sử dụng hard code bằng regex pattern nên vẫn chưa hoàn chỉnh  
* Parser và normalization vẫn đang còn dựa trên mapping tự define