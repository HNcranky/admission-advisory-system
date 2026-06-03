# Agentic Admission Advisory

**Agentic Admission Advisory**

Đây là trang đầu thôi ạ

👈 Bấm các tabs ở bên trái để chuyển mục ạ

# Tổng quan đề tài

Tổng quan đề tài

- Hướng tới xây dựng một agent cho bài toán tư vấn tuyển đại học tại Việt Nam  
- Tập trung vào các trường đại diện ở Hà Nội, bao gồm top 10 hoặc 20 trường đại học nổi bật.  
- Xây dựng một nền tảng có khả năng thu thập, chuẩn hóa, quản lý và sử dụng tri thức tuyển sinh từ các nguồn chính thức: trang fanpage tuyển sinh, website nhà trường, thông tư Bộ giáo dục, … để hỗ trợ tư vấn một cách đáng tin cậy, có căn cứ và có cá nhân hóa theo hồ sơ học sinh.  
- Thực tế, các thông tin này thường phân tán trên nhiều nguồn khác nhau, dưới nhiều định dạng khác nhau. Dữ liệu có tính không đồng nhất cao, thường xuyên thay đổi theo thời gian và đôi khi tồn tại mâu thuẫn giữa các nguồn hoặc giữa các phiên bản công bố. Điều đó khiến việc xây dựng một hệ thống tư vấn tuyển sinh tự động trở nên khó khăn nếu chỉ dựa trên cách tiếp cận FAQ chatbot hay RAG đơn thuần  
- Vì vậy, đề tài này đề xuất một hướng tiếp cận mang tính hệ thống hơn: xây dựng một pipeline ingestion đa nguồn, đa định dạng; sau đó trích xuất và chuẩn hóa dữ liệu tuyển sinh thành các thực thể và quan hệ có cấu trúc. Trên nền dữ liệu đó, hệ thống tiếp tục kiểm tra freshness, phát hiện conflict ở cấp field, quản lý xuất xứ để chỉ đưa vào lớp tri thức chuẩn những thông tin đủ tin cậy.  
- Ở lớp trên cùng, hệ thống sử dụng policy-driven orchestration để hỗ trợ người dùng theo hướng tư vấn. Hệ thống có thể tiếp nhận hồ sơ học sinh ở mức đầy đủ hoặc chưa đầy đủ, xây dựng student profile, đối chiếu với dữ liệu tuyển sinh đã chuẩn hóa, và đưa ra các gợi ý về mức độ phù hợp, chiến lược chọn nguyện vọng, hoặc cảnh báo về rủi ro và tính chưa chắc chắn của thông tin.

# Kiến trúc tổng thể

Workflow

I. Kiến trúc tổng thể

User Query  
   ↓  
\[1\] Intent \+ Profile Builder  
   ↓  
\[2\] Missing Info Detector  
   ↓  
\[3\] Candidate Retrieval (DB)  
   ↓  
\[4\] Eligibility Filter (rule-based)  
   ↓  
\[5\] Conflict \+ Freshness Check  
   ↓  
\[6\] Scoring & Ranking  
   ↓  
\[7\] Answer Policy Decision  
   ↓  
\[8\] Explanation Generator (LLM)  
   ↓  
\[9\] Follow-up Question Generator

1\. Intent \+ profile builder

* hiểu user hỏi gì  
* extract thông tin  
* update profile

2\. Missing info detector

* xác định thiếu gì

3\. Candidate Retrieval

* lấy danh sách ngành/trường phù hợp

4\. Eligibility Filter (rule-based)

Loại:

* không đúng tổ hợp  
* không đúng phương thức  
* không đủ điều kiện

5\. Conflict \+ Freshness Check

kiểm tra dữ liệu có:

* conflict không  
* stale không

6\. Scoring & Ranking

* Tính điểm phù hợp

7\. Answer Policy Decision

* quyết định kiểu trả lời

8\. Explanation Generator (LLM)

9\. Follow-up Question Generator

* hỏi thêm thông tin

# 1\. Xây dựng profile user

Vấn đề xây dựng profile user

I. Kiến trúc tổng thể

User Input  
   ↓  
Intent \+ Entity Extraction  
   ↓  
Profile Builder  
   ↓  
Normalization \+ Validation  
   ↓  
Missing Field Detection  
   ↓  
Profile Storage  
   ↓  
Iterative Update (multi-turn)

II. Thiết kế schema profile  
	1\. Học lực  
	2\. Sở thích  
	3\. Ràng  buộc  
	4\. Lợi thế  
	5\. Metadata

III. Cách build profile từ input user  
	1\. Parse Input  
	2\. Extract entities:  
		Dùng LLM+rule-based  
	3\. Normalize  
	4\. Merge vào profile  
	5\. Detect missing fields

# 2\. Multi Agent Reasoning

Multi-Agent Reasoning

**I. Ingestion**

Document  
  ↓  
Extraction Agent  
  ↓  
Normalization Agent  
  ↓  
Validation Agent  
  ↓  
Conflict Detection Agent

**II. Advisory**

User  
 ↓  
Profile Agent  
 ↓  
Retrieval Agent  
 ↓  
Reasoning Agent  
 ↓  
Policy Agent  
 ↓  
Explanation Agent

**III. Conflict handling**

Conflicting facts  
   ↓  
Evidence Agent  
   ↓  
Comparison Agent  
   ↓  
Resolution Agent  
   ↓  
Decision Policy

# 1\. Dữ liệu phân tán và dị thể

Vấn đề dữ liệu tuyển sinh phân tán và dị thể

I. Bản chất vấn đề

Thông tin tuyển sinh không nằm trong một cơ sở dữ liệu thống nhất, mỗi trường công bố theo các riêng:

* Website tuyển sinh chính  
* Website trường  
* Fanpage facebook  
* Đề án tuyển sinh PDF  
* Trang khoa hoặc trang ngành

Không chỉ phân tán về nguồn, mà còn về định dạng và cách diễn đạt

Ví dụ cùng một thông tin “phương thức xét điểm thi THPT” có thể được viết thành:

* xét tuyển bằng kết quả thi tốt nghiệp THPT  
* sử dụng kết quả kỳ thi THPT  
* xét điểm thi THPT năm 2026  
* phương thức 100: điểm thi tốt nghiệp

II. Hướng giải quyết

Xây dựng pipeline nhiều tầng:

1. Source Registry

	Thay vì hard-code link từng trường, xây dựng một source registry để quản lý mọi nguồn chính thức.

Mỗi source có:  
`school_id`  
`source_id`  
`source_type`

* `admission_homepage`  
* `news_listing`  
* `proposal_pdf`  
* `docx_notice`  
* `facebook_page`  
* `program_page`  
  `root_url`  
  `trust_level`  
  `priority`  
  `fetch_strategy`  
  `parser_profile`  
  `update_frequency_hint`  
  `is_official`  
  `active`

Nhờ source registry, hệ thống có thể:

* biết nguồn nào nên crawl kiểu gì  
* biết parser nào nên dùng  
* biết nguồn nào ưu tiên hơn trong conflict resolution sau này

2. Discovery Layer

	Lớp phát hiện tài nguyên mới

* Quét trang danh mục tuyển sinh  
* Quét feed tin tức  
* Tìm link PDF/DOCX mới  
* Phát hiện link có keyword tuyển sinh  
* Thu link từ bài Facebook dẫn về từ website  
* V..v..

	  
	Output

* URL  
* source\_id  
* discovered\_at  
* predicted\_type  
* priority\_score  
3. Fetch Layer

	Nhiều chế độ fetch:

* HTTP fetch cho HTML/PDF/DOCX  
* Browser rendering cho site dùng JS  
* API fetch cho nguồn có API

	Mỗi fetch cần lưu:

* Raw content  
* Header  
* Content type  
* HTTP status  
* Fetched\_at  
* Content hash  
* Final URL  
4. Document Router

	Sau khi fetch, hệ thống phải phân loại tài liệu thành: html\_article, pdf\_text, pdf\_scanned, docx, image, facebook\_post,... Vì từng loại tài liệu sẽ phù hợp với từng parser khác nhau.

5. Parsing Layer  
* HTML Parsing  
* PDF Parsing  
* DOCX parsing  
* OCR fallback  
6. Schema-Driven Extraction

	Extract theo schema mục tiêu:

* school\_name  
* admission\_year  
* program\_name  
* program\_code  
* admission\_method\_raw  
* subject\_combinations\_raw  
* quota\_raw  
* deadline\_raw  
* additional\_conditions\_raw  
* tuition\_raw  
* source\_reference

7. Normalization Layer

	Đây là lớp biến extracted facts thành tri thức có thể dùng

* map tên ngành raw → canonical program  
* map phương thức raw → taxonomy chuẩn  
* chuẩn hóa tổ hợp môn  
* parse quota thành numeric field  
* parse deadline thành structured date/range  
* chuẩn hóa điều kiện phụ thành JSON/rule objects

# 2\. Vấn đề dữ liệu thay đổi theo thời gian

Vấn đề dữ liệu thay đổi theo thời gian

I. Bản chất vấn đề  
Thông tin tuyển sinh không phải dữ liệu tĩnh. Nó thay đổi theo:

* Năm tuyển sinh  
* Đợt tuyển sinh  
* Thông báo điều chỉnh  
* Thay đổi chỉ tiêu  
* Bổ sung hoặc loại bỏ tổ hợp  
* Cập nhật deadline  
* Điều chỉnh điều kiện phụ

II. Hướng giải quyết

1. Incremental crawling  
* Hash nội dung  
* Recrawl theo lịch  
* Chỉ parse lại khi có thay đổi  
2. Versioned evidence storage

	Mỗi tài liệu hoặc snapshot phải có:

* Fetched\_at  
* Published\_at  
* Content\_hash  
* Source version  
3. Field-level change detection

	So sánh các field quan trọng:

* Quota  
* Deadline  
* Combinations (Tổ hợp)  
* Conditions  
4. Freshness status

	Mỗi fact canonical nên có:

* Last\_verified\_at  
* Freshness\_score

# 3\. Vấn đề xung đột dữ liệu

Vấn đề xung đột dữ liệu

I. Bản chất vấn đề  
Cùng một field có thể có nhiều giá trị khác nhau từ nhiều nguồn:

* Đề án ghi một giá trị  
* Website ghi giá trị khác  
* Fanpage thông báo khác  
* Tài liệu mới chưa đồng bộ với tài liệu cũ


II. Hướng giải quyết

1. Critical field list

	Chỉ các field quan trọng mới đi qua conflict gate mạnh:

* Quota  
* Deadline  
* Combinations (Tổ hợp môn)  
* Conditions  
2. Entity alignment

	So sánh phải trên cùng khóa logic:  
	(school, year, program, method, scope)

3. Conflict detection

	Nếu cùng field mà khác value → sinh conflict candidate

4. Resolution policy

	Ví dụ:

official update \> proposal

university official website \> Facebook

newer source \> older source

nếu không đủ chắc chắn → unresolved

5. Answer policy

	Nếu unresolved conflict ở field critical → không trả lời như fact chắc chắn

# 4\. Vấn đề chuẩn hóa tri thức tuyển sinh

Vấn đề chuẩn hóa tri thức tuyển sinh thành cấu trúc dùng được

I. Bản chất vấn đề

Ngay cả khi đã extract được text, thì mới chỉ có được dữ liệu bán cấu trúc hoặc text thô.

Để có thể tư vấn, cần phải chuẩn hóa các khái niệm như:

* Trường  
* Chương trình  
* Ngành  
* Phương thức xét tuyển  
* Tổ hợp môn  
* Quota  
* Thời hạn  
* Phạm vi áp dụng

II. Hướng giải quyết

### **1\. Thiết kế taxonomy admission methods**

Ví dụ phân tầng:

* Exam\_based: Thi THPT  
* Transcript\_based: Hồ sơ năng lực  
* Direct\_admission: Tuyển thẳng  
* Competency\_test: Đánh giá tư duy  
* Combined\_method: Xét tuyển kết hợp

### **2\. Thiết kế schema lai relational \+ JSONB**

* relational cho entity cốt lõi  
* JSONB cho điều kiện phức tạp, raw mapping, parser metadata

### **3\. Chuẩn hóa raw → canonical**

* raw\_method\_text → canonical\_method\_type  
* raw\_program\_name → canonical\_program  
* raw\_combination\_text → canonical subject combinations

# 5\. Vấn đề tư vấn cá nhân hóa

Vấn đề tư vấn cá nhân hóa khi hồ sơ học sinh thiếu, mơ hồ, hoặc chưa hoàn chỉnh

I. Bản chất vấn đề

Người dùng hiếm khi cung cấp profile đầy đủ. Họ thường hỏi kiểu:

* Em khoảng 24–25 điểm A01 thì nên chọn trường nào?  
* Em muốn học kinh tế ở Hà Nội nhưng nhà em tài chính vừa phải.  
* Em thích CNTT nhưng chưa biết nên chọn trường top hay an toàn.  
* Em có IELTS nhưng chưa rõ có lợi thế gì.

Những đầu vào này:

* thiếu trường thông tin quan trọng  
* có yếu tố định tính  
* đôi khi chỉ là ước lượng  
* có thể không đủ để kết luận chắc chắn

II. Hướng giải quyết

### **1\. Student profile model**

Nên có các nhóm trường:

* academic signals  
* preferences  
* constraints  
* supporting certificates  
* uncertainty / completeness

Ví dụ:

 ![][image1]

### **2\. Missing-field-aware reasoning**

Hệ thống không nên dừng hoàn toàn khi thiếu dữ liệu, mà nên:

* tư vấn sơ bộ  
* ghi rõ còn thiếu gì  
* phân nhóm gợi ý theo mức độ chắc chắn

### **3\. Output theo nhóm thay vì kết luận cứng**

Ví dụ:

* phù hợp cao  
* cân nhắc thêm  
* cạnh tranh cao  
* phương án an toàn

[image1]: <data:image/png;base64,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>