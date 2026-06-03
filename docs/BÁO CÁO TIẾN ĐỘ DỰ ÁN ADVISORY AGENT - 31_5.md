# BÁO CÁO TIẾN ĐỘ DỰ ÁN ADVISORY AGENT

**Ngày báo cáo:** 31/05/2026
**Phạm vi:** Rà soát toàn bộ codebase, đánh giá những gì đã hoàn thành và những gì còn thiếu.

---

## 1. Tóm tắt cho người quản lý

Dự án xây dựng một **trợ lý tư vấn tuyển sinh đại học** cho thí sinh Việt Nam. Hệ
thống tự động thu thập thông tin tuyển sinh từ nguồn chính thức của các trường,
chuẩn hóa dữ liệu về một kho lưu trữ thống nhất, rồi phục vụ một giao diện chat
để hỏi đáp, thu thập hồ sơ học sinh và đưa ra gợi ý ngành/trường phù hợp.

Điểm nổi bật của hệ thống là **nhận biết được mâu thuẫn dữ liệu** giữa các nguồn
(ví dụ: chỉ tiêu của cùng một ngành nhưng hai nguồn ghi khác nhau) và tự động xử
lý, giải thích cho người dùng — đây là giá trị cốt lõi tạo sự khác biệt.

So với báo cáo gần nhất (11/04), dự án đã đi từ trạng thái "có khung sườn, suy
luận bằng quy tắc cứng" sang trạng thái **chạy được đầu-cuối (end-to-end)**: từ
lúc người dùng gõ tin nhắn cho tới khi nhận được tư vấn hoàn chỉnh, có giao diện
web hoàn thiện và có cả bảng theo dõi quá trình xử lý của hệ thống theo thời gian
thực.

**Đánh giá chung:** Phần lõi (chat, tư vấn, xử lý mâu thuẫn, thu thập dữ liệu hai
trường lớn) đã sẵn sàng để demo và dùng thử. Phần còn thiếu chủ yếu nằm ở **độ
phủ dữ liệu** (mới có 2 trong số nhiều trường mục tiêu) và một số tính năng nâng
cao chưa làm (tìm kiếm ngữ nghĩa, đọc tài liệu dạng ảnh quét).

---

## 2. Kiến trúc tổng thể

Hệ thống gồm bốn khối lớn, hoạt động độc lập nhưng kết nối qua một kho dữ liệu
chung trên PostgreSQL:

1. **Khối thu thập & chuẩn hóa dữ liệu (Ingestion)** — lấy dữ liệu từ website và
   file PDF của các trường, bóc tách rồi chuẩn hóa về định dạng thống nhất.
2. **Khối tư vấn (Advisory pipeline)** — chuỗi sáu bước xử lý lần lượt một câu hỏi
   của học sinh thành lời tư vấn.
3. **Khối dịch vụ nền (Services)** — chứa logic thực thi mà các bước tư vấn gọi
   đến: gọi mô hình AI, quản lý phiên chat, phát hiện mâu thuẫn, ghi vết xử lý.
4. **Khối giao diện web (Web)** — máy chủ web và giao diện chat cho người dùng cuối.

---

## 3. Tình trạng từng khối

### 3.1. Khối tư vấn (Advisory pipeline) — ✅ HOÀN THÀNH

Đây là "bộ não" của hệ thống, gồm sáu bước xử lý nối tiếp nhau. Toàn bộ sáu bước
đã được hiện thực đầy đủ, không còn phần để trống hay tạm bợ:

| Bước | Chức năng | Tình trạng |
|------|-----------|------------|
| **Profile** (lập hồ sơ) | Đọc câu hỏi của học sinh, dùng AI bóc tách thông tin: điểm số, tổ hợp môn, ngành/trường mong muốn, khu vực, ngân sách học phí. Ghi nhận các thông tin còn thiếu. | Hoàn thành |
| **Retrieve** (truy xuất) | Dựa trên hồ sơ, truy vấn kho dữ liệu để lấy ra các ngành/chương trình ứng viên phù hợp, kèm theo nguồn gốc và độ tin cậy của từng dữ liệu. | Hoàn thành |
| **Conflict** (xử lý mâu thuẫn) | Phát hiện các trường hợp dữ liệu mâu thuẫn giữa nhiều nguồn, xếp hạng nguồn theo độ tin cậy/độ mới/mức độ được nhiều nguồn xác nhận, và nhờ AI phân xử khi không thể quyết định bằng quy tắc. | Hoàn thành |
| **Reason** (suy luận) | Chấm điểm mức độ phù hợp của từng ngành với hồ sơ học sinh (theo tổ hợp môn, ngành, trường, vùng điểm), phân loại thành các nhóm an toàn / phù hợp / mạo hiểm. | Hoàn thành |
| **Policy** (kiểm soát) | Áp các quy tắc an toàn: không hứa hẹn chắc chắn đỗ, không dự đoán xác suất khi thiếu điểm, cảnh báo khi dữ liệu còn mâu thuẫn hoặc hồ sơ còn thiếu. | Hoàn thành |
| **Explain** (giải thích) | Soạn câu trả lời tư vấn hoàn chỉnh **bằng tiếng Việt**: tóm tắt hồ sơ, top gợi ý kèm lý do và lưu ý, trích dẫn nguồn, ghi chú phần dữ liệu đã được đối chiếu. | Hoàn thành |

**Điểm mạnh đáng ghi nhận:**
- Mỗi bước đều có cơ chế **suy giảm an toàn (graceful degradation)**: nếu lệnh gọi
  AI thất bại, hệ thống tự lùi về phương án xử lý tất định (bằng quy tắc) thay vì
  báo lỗi cho người dùng.
- Việc suy luận và chấm điểm chủ yếu **dựa trên quy tắc tất định**, AI chỉ đóng
  vai hỗ trợ ở một số điểm (bóc tách hồ sơ, phân xử mâu thuẫn). Cách làm này giúp
  kết quả ổn định và dễ giải thích.
- Toàn bộ kết quả trả về cho người dùng đã được Việt hóa.

### 3.2. Khối thu thập & chuẩn hóa dữ liệu (Ingestion) — ⚠️ HOÀN THÀNH PHẦN LÕI, THIẾU ĐỘ PHỦ

Quy trình thu thập đi qua các chặng: **lấy dữ liệu → phân loại tài liệu → bóc tách
→ chuẩn hóa → ghi vào kho**. Toàn bộ chuỗi này đã chạy được đầu-cuối.

**Đã hoàn thành:**
- **Module lấy dữ liệu (Fetcher):** tải được nội dung web/PDF, có cơ chế thử lại
  nhiều lần khi mạng lỗi, xoay vòng "danh tính trình duyệt" để tránh bị chặn. Cố
  ý **tắt kiểm tra chứng chỉ SSL** vì nhiều cổng thông tin chính thức của các
  trường (.gov.vn) có chứng chỉ hỏng — đây là lựa chọn có chủ đích và được ghi log.
- **Module bóc tách (Extractor):** dùng kết hợp **quy tắc regex (ưu tiên) và AI
  (dự phòng)**. Nếu bóc tách bằng quy tắc cho độ tin cậy thấp thì mới gọi AI, giúp
  tiết kiệm chi phí.
- **Module chuẩn hóa (Normalizer):** ánh xạ tên ngành, phương thức xét tuyển, tổ
  hợp môn và chỉ tiêu về dạng chuẩn, dựa trên bộ từ điển riêng cho từng trường.
  Có cả cơ chế **suy ra phương thức xét tuyển từ mã tổ hợp** khi nguồn không ghi rõ.
- **Hai trường đã thu thập thành công và đang chạy thật:**
  - **Đại học Bách khoa Hà Nội (HUST)** — 2 nguồn, khoảng 136 bản ghi đã chuẩn hóa.
  - **Đại học Công nghệ - ĐHQGHN (VNU-UET)** — 2 nguồn (trang web + PDF đề án),
    khoảng 40 bản ghi, và **đã xác nhận phát hiện được mâu thuẫn chỉ tiêu giữa hai
    nguồn** — chứng minh tính năng cốt lõi hoạt động trên dữ liệu thật.

**Còn thiếu / chưa hoàn thiện:**
- **Đại học Kinh tế Quốc dân (NEU)** và **Đại học Ngoại thương (FTU):** đã chuẩn bị
  sẵn từ điển ngành và phương thức, nhưng **chưa khai báo nguồn dữ liệu**, nên chưa
  thu thập được. Đây là việc còn lại rõ ràng nhất về mặt mở rộng độ phủ.
- **Đọc file Word (.docx):** chưa hiện thực, hiện trả về rỗng.
- **Đọc PDF dạng ảnh quét (OCR):** hệ thống nhận biết được PDF là ảnh quét nhưng
  chưa có khả năng nhận dạng chữ trong ảnh.
- **Lấy dữ liệu qua trình duyệt giả lập và qua API:** đã có chỗ dành sẵn nhưng hiện
  vẫn quay về cách tải HTTP thông thường.
- **Lưu ý chất lượng:** một số trang chi tiết của HUST không bóc được chỉ tiêu,
  dẫn tới tín hiệu mâu thuẫn giả — cần rà lại bộ bóc tách.

### 3.3. Khối dịch vụ nền (Services)

Khối này chứa các module logic mà khối tư vấn gọi đến. Tình trạng chi tiết:

| Module | Chức năng | Tình trạng |
|--------|-----------|------------|
| **Inference (cổng gọi AI)** | Cổng thống nhất cho mọi lệnh gọi mô hình Gemini, có cơ chế thử lại, dự phòng sang model nhẹ hơn, và ghi nhận thông số (telemetry). | ✅ Hoàn thành (mới chỉ hỗ trợ nhà cung cấp Gemini) |
| **Chat (quản lý phiên)** | Quản lý phiên chat ẩn danh, lưu lịch sử tin nhắn, theo dõi trạng thái hồ sơ, điều phối việc chạy tư vấn ở luồng nền. | ✅ Hoàn thành |
| **Conflict (xử lý mâu thuẫn)** | Phát hiện mâu thuẫn, xếp hạng nguồn tất định, gọi AI phân xử khi cần. | ✅ Hoàn thành |
| **Tracing (ghi vết xử lý)** | Ghi lại từng bước xử lý của hệ thống để hiển thị lên bảng theo dõi, kèm thời gian và kết quả từng bước. | ✅ Hoàn thành |
| **Retrieval (truy xuất có dẫn nguồn - RAG)** | Lấy dữ liệu ứng viên từ kho chuẩn hóa, gắn nguồn/độ tin cậy, làm đầu vào cho bước sinh câu trả lời. | ✅ Hoàn thành (dùng lọc SQL) |

**Lưu ý về luồng RAG (truy xuất + sinh câu trả lời có dẫn nguồn):** Luồng cốt lõi
của RAG **đã được hiện thực và đang chạy**: bước truy xuất lấy các ngành ứng viên
từ kho dữ liệu chuẩn hóa, gắn kèm bằng chứng (nguồn, năm, độ tin cậy) cho từng dữ
liệu; sau đó bước sinh câu trả lời tạo lời tư vấn tiếng Việt **bám sát dữ liệu lấy
được và trích dẫn nguồn rõ ràng**. Hiện luồng này dùng **truy vấn lọc trực tiếp
trên cơ sở dữ liệu** (kèm khớp gần đúng theo tên ngành) thay vì tìm kiếm ngữ nghĩa
bằng vector. Phần **nâng cấp lên tìm kiếm ngữ nghĩa (vector/pgvector)** — như tài
liệu kiến trúc dự kiến — là hạng mục **còn bỏ ngỏ** (xem mục Còn thiếu), nhưng đây
là cải tiến chất lượng truy xuất chứ không phải điều kiện để luồng hoạt động.

### 3.4. Khối giao diện web (Web) — ✅ HOÀN THÀNH

- **Máy chủ web (FastAPI)** với các nhóm endpoint: kiểm tra sức khỏe hệ thống,
  trang chat, và API phiên chat (tạo phiên, gửi tin nhắn, lấy trạng thái, lấy vết
  xử lý).
- **Giao diện chat** bố cục 3 cột linh hoạt: cột trái hiển thị hồ sơ và gợi ý, cột
  giữa là khung chat, cột phải là bảng theo dõi 6 bước xử lý.
- **Các tính năng đã hoàn thiện:** giao diện co giãn theo màn hình (responsive),
  chuyển đổi giao diện sáng/tối, thông báo dạng toast, hỗ trợ phím tắt, có chú ý
  về khả năng truy cập (accessibility), thông báo lỗi bằng tiếng Việt.
- **Bảng theo dõi (Trace panel):** hiển thị tiến trình 6 bước theo thời gian thực,
  có chế độ debug để xem chi tiết kết quả từng bước (bật bằng biến môi trường).
- **Luồng chat chạy thông suốt đầu-cuối:** gửi tin nhắn → bóc tách hồ sơ → hỏi
  thêm nếu thiếu thông tin → chạy tư vấn ở luồng nền → giao diện tự cập nhật kết
  quả khi xong.

**Điểm cần cải thiện (nhỏ):** phần hiển thị debug còn ở dạng JSON thô, chưa được
trình bày đẹp; tuy nhiên đây chỉ là công cụ cho lập trình viên, không ảnh hưởng
người dùng cuối.

### 3.5. Cơ sở dữ liệu (Database)

- Gồm **11 migration** đánh số tuần tự, có tính idempotent (chạy lại nhiều lần
  không gây lỗi).
- **Bảng cốt lõi** là kho dữ liệu tuyển sinh chuẩn hóa: lưu mỗi bản ghi theo
  trường / ngành / phương thức / năm, kèm chỉ tiêu, tổ hợp môn, hạn nộp, học phí
  (dạng JSONB linh hoạt), cùng nguồn gốc và độ tin cậy.
- Thiết kế cho phép **cùng một ngành nhưng đến từ nhiều nguồn khác nhau được lưu
  thành các dòng riêng** — đây chính là nền tảng để phát hiện mâu thuẫn.
- Có đầy đủ bảng cho **phiên chat, tin nhắn, lần chạy tư vấn, và vết xử lý**.

**Một điểm nợ kỹ thuật cần dọn:** tồn tại song song hai bảng lưu lần chạy tư vấn —
một bảng cũ (`advisory_runs`) hiện không còn được code dùng đến, và một bảng mới
đang dùng thật. Nên xóa hoặc làm rõ bảng cũ để tránh nhầm lẫn về sau.

---

## 4. Chất lượng & kiểm thử

- **Bộ kiểm thử (test):** khoảng **61 file test** với hơn **170 test case**, phủ
  các phần: các bước tư vấn, cổng gọi AI (thử lại/dự phòng), logic phát hiện và
  xử lý mâu thuẫn, vòng đời phiên chat, các bộ bóc tách dữ liệu, và giao diện web.
- **Hạ tầng test trưởng thành:** có sẵn các đối tượng giả lập (fake gateway, fake
  repository) để test mà không cần gọi AI thật; test tích hợp/đầu-cuối tự động bỏ
  qua một cách rõ ràng khi chưa bật cơ sở dữ liệu Docker.
- **Khoảng trống:** chưa có test tích hợp cho toàn bộ luồng chat web (từ gửi tin
  nhắn tới khi hoàn tất); chưa có test cho hai trường NEU và FTU (vì chưa có nguồn).

---

## 5. Mức độ sẵn sàng vận hành & cách cài đặt

- **Cài đặt đã được kịch bản hóa hoàn toàn:** một lệnh khởi tạo lo trọn bộ môi
  trường ảo, thư viện, file cấu hình, cơ sở dữ liệu Docker và chạy migration.
- **Có tài liệu QUICKSTART** hướng dẫn từng bước, kèm chế độ demo dữ liệu giả lập
  để thử nhanh mà không cần dữ liệu thật.
- **Bí mật (khóa API Gemini)** được giữ riêng trong file môi trường, không đưa vào
  mã nguồn.

**Đánh giá:** mức độ trưởng thành về cài đặt/triển khai là **cao**.

---

## 6. Tổng hợp: Đã đạt được vs Còn thiếu

### ✅ Đã đạt được
- Toàn bộ chuỗi tư vấn 6 bước hoàn chỉnh, có Việt hóa, có cơ chế dự phòng an toàn.
- **Luồng RAG (truy xuất + sinh câu trả lời có dẫn nguồn)** hoạt động đầu-cuối:
  lấy dữ liệu từ kho chuẩn hóa, gắn nguồn, và sinh tư vấn tiếng Việt có trích dẫn.
- Tính năng cốt lõi — **phát hiện và xử lý mâu thuẫn dữ liệu** — hoạt động trên
  dữ liệu thật của VNU-UET.
- Giao diện chat web hoàn thiện, chạy thông suốt đầu-cuối, có bảng theo dõi xử lý.
- Cổng gọi AI có thử lại/dự phòng, có ghi nhận thông số.
- Thu thập dữ liệu thành công 2 trường (HUST, VNU-UET).
- Cơ sở dữ liệu chuẩn hóa đầy đủ, hỗ trợ đa nguồn.
- Bộ kiểm thử rộng và hạ tầng cài đặt trưởng thành.

### ⚠️ Còn thiếu / cần làm tiếp (ưu tiên cao)
- **Mở rộng độ phủ trường:** kích hoạt thu thập cho NEU và FTU (đã chuẩn bị từ
  điển, chỉ thiếu khai báo nguồn), và tiến tới các trường mục tiêu khác.
- **Rà lại chất lượng bóc tách HUST** để tránh tín hiệu mâu thuẫn giả.
- **Dọn nợ kỹ thuật cơ sở dữ liệu:** xử lý bảng lần-chạy-tư-vấn cũ không còn dùng.
- **Đồng bộ tài liệu kiến trúc với thực tế** (đặc biệt phần module Knowledge và số
  lượng migration).

### ❌ Chưa làm (tính năng nâng cao)
- **Nâng cấp truy xuất lên tìm kiếm ngữ nghĩa bằng vector (pgvector):** luồng RAG
  hiện chạy bằng lọc SQL; bản nâng cấp dùng embedding/vector như tài liệu kiến trúc
  dự kiến thì chưa làm. Đây là cải tiến chất lượng, không phải hạng mục chặn vận hành.
- **Đọc tài liệu nâng cao:** file Word (.docx) và PDF dạng ảnh quét (OCR).
- **Cách lấy dữ liệu nâng cao:** qua trình duyệt giả lập, qua API có xác thực.
- **Vận hành dài hạn:** chưa có cơ chế hết hạn/dọn dẹp phiên chat cũ, chưa có giới
  hạn tần suất gọi theo người dùng, và thông số telemetry mới chỉ ghi trong bộ nhớ
  chứ chưa xuất ra hệ thống giám sát.

---

## 7. Đề xuất các bước tiếp theo

1. **Ngắn hạn:** khai báo nguồn và chạy thu thập cho NEU, FTU để tăng nhanh độ phủ;
   rà lại bộ bóc tách HUST.
2. **Trung hạn:** dọn nợ kỹ thuật cơ sở dữ liệu; bổ sung test tích hợp cho luồng
   chat web; cập nhật lại tài liệu kiến trúc cho khớp thực tế.
3. **Dài hạn:** nâng cấp luồng truy xuất hiện có lên **tìm kiếm ngữ nghĩa bằng
   vector (pgvector)** để cải thiện chất lượng truy xuất; bổ sung OCR cho tài liệu
   ảnh quét; chuẩn bị các cơ chế vận hành dài hạn
   (dọn phiên, giới hạn tần suất, xuất telemetry ra hệ thống giám sát).
