# BÁO CÁO TIẾN ĐỘ DỰ ÁN ADVISORY AGENT

**Ngày báo cáo:** 31/05/2026
**Phạm vi:** Rà soát lại toàn bộ codebase ở thời điểm hiện tại, đánh giá những gì đã
hoàn thành và những gì còn thiếu. Bản này cập nhật so với báo cáo cùng ngày, phản
ánh các thay đổi mới nhất trong mã nguồn.

---

## 1. Tóm tắt cho người quản lý

Dự án xây dựng một **trợ lý tư vấn tuyển sinh đại học** cho thí sinh Việt Nam. Hệ
thống tự động thu thập thông tin tuyển sinh từ nguồn chính thức của các trường,
chuẩn hóa dữ liệu về một kho lưu trữ thống nhất, rồi phục vụ một giao diện chat
để hỏi đáp, thu thập hồ sơ học sinh và đưa ra gợi ý ngành/trường phù hợp.

Giá trị cốt lõi tạo khác biệt là **nhận biết được mâu thuẫn dữ liệu** giữa các
nguồn (ví dụ: chỉ tiêu của cùng một ngành nhưng hai nguồn ghi khác nhau), tự động
xếp hạng nguồn để phân xử và giải thích minh bạch cho người dùng.

**So với lần rà soát trước, hệ thống đã tiến thêm một bước quan trọng về chiều
sâu:** từ chỗ chỉ có một luồng tư vấn theo hồ sơ, nay đã có **bộ định tuyến ý định
(intent router)** phân loại câu hỏi người dùng thành nhiều luồng khác nhau, và có
thêm **một phân hệ hỏi-đáp kiến thức bằng tìm kiếm ngữ nghĩa (vector/RAG)** chạy
thật trên cơ sở dữ liệu — đây vốn là hạng mục từng được liệt vào "chưa làm" ở các
báo cáo trước.

**Đánh giá chung:** Phần lõi đã **chạy được đầu-cuối (end-to-end)** và sẵn sàng
demo/dùng thử: chat, định tuyến câu hỏi, tư vấn theo hồ sơ, hỏi-đáp kiến thức theo
ngữ nghĩa, so sánh trường, phát hiện và xử lý mâu thuẫn, cùng giao diện web hoàn
chỉnh có bảng theo dõi quá trình xử lý theo thời gian thực. Phần còn thiếu chủ yếu
nằm ở **độ phủ dữ liệu** (mới có 2 trong số các trường mục tiêu) và một vài hạng
mục thu thập nâng cao (đọc file Word, đọc PDF dạng ảnh quét).

---

## 2. Kiến trúc tổng thể

Hệ thống gồm bốn khối lớn, hoạt động độc lập nhưng kết nối qua một kho dữ liệu
chung trên cơ sở dữ liệu PostgreSQL:

1. **Khối thu thập & chuẩn hóa dữ liệu (Ingestion)** — lấy dữ liệu từ website và
   file PDF của các trường, bóc tách rồi chuẩn hóa về định dạng thống nhất. Khối
   này nuôi đồng thời hai kho: kho dữ liệu tuyển sinh có cấu trúc (chỉ tiêu, tổ
   hợp, phương thức) và kho tài liệu kiến thức dạng văn bản (học phí, học bổng,
   chương trình học…).
2. **Khối dịch vụ nền (Services)** — chứa toàn bộ logic thực thi: cổng gọi mô hình
   AI, quản lý phiên chat, định tuyến ý định, hỏi-đáp kiến thức theo ngữ nghĩa,
   phát hiện mâu thuẫn, ghi vết xử lý.
3. **Khối tư vấn (Advisory pipeline)** — chuỗi sáu bước xử lý lần lượt một câu hỏi
   của học sinh thành lời tư vấn có dẫn nguồn.
4. **Khối giao diện web (Web)** — máy chủ web và giao diện chat cho người dùng cuối.

---

## 3. Tình trạng từng khối

### 3.1. Khối định tuyến & hội thoại (Chat) — ✅ HOÀN THÀNH

Đây là phần mới được mở rộng đáng kể và là "người gác cổng" cho toàn hệ thống. Mỗi
tin nhắn của người dùng đều đi qua **bộ định tuyến ý định (intent router)** — dùng
AI để phân loại câu hỏi vào một trong sáu luồng:

| Luồng | Khi nào dùng | Hệ thống làm gì |
|-------|--------------|-----------------|
| **Trò chuyện** | Chào hỏi, cảm ơn, hỏi về danh tính/khả năng của trợ lý | Trả lời ngay bằng câu mẫu, không chạy tư vấn |
| **Hỏi-đáp kiến thức** | Hỏi thông tin cụ thể về một trường/ngành (học phí, học bổng, chương trình học…) | Tìm kiếm ngữ nghĩa trong kho tài liệu, sinh câu trả lời có trích dẫn |
| **Luồng tư vấn** | Cần thu thập hồ sơ và xếp hạng gợi ý ngành/trường | Hỏi thêm thông tin còn thiếu rồi chạy chuỗi tư vấn 6 bước |
| **Hybrid (kết hợp)** | Vừa cần dữ liệu điểm/khả năng đỗ vừa cần thông tin kiến thức (ví dụ "so sánh học phí kèm khả năng đỗ") | Chạy song song cả hai nhánh rồi tổng hợp lại |
| **Làm rõ** | Câu hỏi mơ hồ, thiếu thông tin then chốt | Hỏi lại để làm rõ |
| **Ngoài phạm vi** | Không liên quan tuyển sinh | Lịch sự từ chối |

**Điểm mạnh đáng ghi nhận:**
- Bộ định tuyến biết **chuẩn hóa chủ đề về một tập cố định** (học phí, chương trình,
  học bổng, ký túc xá, nghề nghiệp, quy chế tuyển sinh, giới thiệu ngành) và **giải
  nghĩa đại từ** (ví dụ "trường này" sẽ được hiểu là trường đang nhắc tới trong hồ sơ).
- Có cơ chế **dự phòng an toàn**: nếu lệnh gọi AI thất bại, hệ thống tự lùi về luồng
  tư vấn mặc định thay vì báo lỗi.
- Đã có sửa lỗi đảm bảo một chủ đề lạ không làm câu hỏi kiến thức bị định tuyến nhầm
  sang luồng tư vấn.

Các luồng tư vấn và hybrid được chạy ở **luồng nền (background)** để không chặn giao
diện: người dùng tiếp tục thấy hệ thống "đang xử lý" và nhận kết quả khi xong. Riêng
luồng hybrid còn có **bước tổng hợp** dùng AI để gộp kết quả tư vấn và kết quả kiến
thức thành một câu trả lời mạch lạc, tuân thủ nguyên tắc chỉ nói những gì có dữ liệu.

### 3.2. Khối hỏi-đáp kiến thức theo ngữ nghĩa (Knowledge / RAG) — ✅ HOÀN THÀNH (ĐIỂM MỚI)

Đây là thay đổi lớn nhất so với các báo cáo trước. **Tìm kiếm ngữ nghĩa bằng vector
(pgvector) nay đã được hiện thực đầy đủ và đang chạy thật**, không còn là hạng mục
bỏ ngỏ.

Cách hoạt động:
- Tài liệu kiến thức của các trường (trang học phí, học bổng, chương trình…) được
  **cắt thành các đoạn nhỏ (chunk)**, mỗi đoạn được chuyển thành một **vector
  embedding** bằng mô hình của Gemini, rồi lưu vào cơ sở dữ liệu.
- Khi người dùng hỏi, câu hỏi cũng được chuyển thành vector, hệ thống **tìm các
  đoạn văn bản gần nghĩa nhất** (theo độ tương đồng cosine), lọc theo ngưỡng độ tin
  cậy, rồi đưa các đoạn này cho AI sinh câu trả lời **bám sát nội dung và trích dẫn
  nguồn rõ ràng**.
- Có **cơ chế tái sử dụng embedding giữa các tài liệu**: hai đoạn văn bản giống hệt
  nhau (nhận biết qua "vân tay" nội dung — content hash) chỉ cần tạo embedding một
  lần, tránh tính lại tốn kém khi thu thập lại dữ liệu.

Phân hệ này được cả luồng "hỏi-đáp kiến thức" và luồng "hybrid" sử dụng. Trong luồng
hybrid, hệ thống có thể **hỏi nhiều trường / nhiều chủ đề cùng lúc (fanout)** rồi gom
kết quả lại để so sánh.

> **Lưu ý phân biệt hai cơ chế truy xuất:** Hệ thống có hai đường lấy dữ liệu khác
> nhau, phục vụ hai mục đích khác nhau, và đây là thiết kế hợp lý:
> - **Truy xuất dữ liệu có cấu trúc** (chỉ tiêu, tổ hợp, phương thức) trong luồng tư
>   vấn — dùng **truy vấn lọc trực tiếp trên cơ sở dữ liệu**, vì đây là dữ liệu bảng
>   biểu chính xác, không cần tìm theo ngữ nghĩa.
> - **Truy xuất tài liệu văn bản tự do** (học phí, học bổng…) trong luồng hỏi-đáp —
>   dùng **tìm kiếm ngữ nghĩa bằng vector**, vì câu hỏi tự nhiên cần khớp theo ý nghĩa.

### 3.3. Khối tư vấn (Advisory pipeline) — ✅ HOÀN THÀNH

Đây là "bộ não" xếp hạng gợi ý, gồm sáu bước xử lý nối tiếp. Toàn bộ sáu bước đã
được hiện thực đầy đủ, không còn phần để trống hay tạm bợ:

| Bước | Chức năng | Tình trạng |
|------|-----------|------------|
| **Lập hồ sơ (Profile)** | Đọc câu hỏi, dùng AI bóc tách thông tin: điểm số, tổ hợp môn, ngành/trường mong muốn, khu vực, ngân sách. Ghi nhận thông tin còn thiếu. | Hoàn thành |
| **Truy xuất (Retrieve)** | Dựa trên hồ sơ, truy vấn kho dữ liệu có cấu trúc để lấy các ngành/chương trình ứng viên, kèm nguồn gốc và độ tin cậy từng dữ liệu. | Hoàn thành |
| **Xử lý mâu thuẫn (Conflict)** | Phát hiện dữ liệu mâu thuẫn giữa nhiều nguồn, xếp hạng nguồn theo độ tin cậy/độ mới/mức độ được nhiều nguồn xác nhận, nhờ AI phân xử khi quy tắc không quyết định được. | Hoàn thành |
| **Suy luận (Reason)** | Chấm điểm mức độ phù hợp từng ngành với hồ sơ (theo tổ hợp, ngành, trường, vùng điểm), phân loại nhóm an toàn / phù hợp / mạo hiểm. | Hoàn thành |
| **Kiểm soát (Policy)** | Áp quy tắc an toàn: không hứa chắc đỗ, không dự đoán xác suất khi thiếu điểm, cảnh báo khi dữ liệu còn mâu thuẫn hoặc hồ sơ còn thiếu. | Hoàn thành |
| **Giải thích (Explain)** | Soạn câu trả lời tư vấn hoàn chỉnh **bằng tiếng Việt**: tóm tắt hồ sơ, top gợi ý kèm lý do và lưu ý, trích dẫn nguồn, ghi chú phần dữ liệu đã đối chiếu. | Hoàn thành |

**Triết lý thiết kế đáng ghi nhận:**
- Bốn trên sáu bước (truy xuất, suy luận, một phần xử lý mâu thuẫn, giải thích) chạy
  **hoàn toàn bằng quy tắc tất định**, AI chỉ hỗ trợ ở vài điểm cần linh hoạt (bóc
  tách hồ sơ, phân xử mâu thuẫn, kiểm tra câu chữ chính sách). Nhờ đó kết quả **ổn
  định và dễ giải thích**.
- Mỗi điểm gọi AI đều có **dự phòng an toàn**: nếu AI lỗi, hệ thống lùi về xử lý
  bằng quy tắc thay vì gãy. Không có lỗi nào bị "nuốt im lặng" — đều được ghi log.
- **Mâu thuẫn được lan truyền minh bạch:** dữ liệu chưa phân xử được sẽ bị đánh dấu
  "chưa chắc chắn"; bước suy luận tự hạ một bậc tin cậy của gợi ý liên quan; bước
  giải thích nêu rõ và khuyên người dùng kiểm chứng lại với nhà trường.

### 3.4. Khối thu thập & chuẩn hóa dữ liệu (Ingestion) — ⚠️ HOÀN THÀNH PHẦN LÕI, THIẾU ĐỘ PHỦ

Quy trình thu thập đi qua các chặng: **lấy dữ liệu → phân loại tài liệu → bóc tách →
chuẩn hóa → ghi vào kho**. Toàn bộ chuỗi này đã chạy được đầu-cuối, và nay đã **ghi
thật vào kho dữ liệu chuẩn hóa** (trước đây có giai đoạn chỉ in kết quả ra mà chưa
lưu — điểm này đã được khắc phục).

**Đã hoàn thành:**
- **Module lấy dữ liệu (Fetcher):** tải được nội dung web/PDF, có thử lại nhiều lần
  khi mạng lỗi, xoay vòng "danh tính trình duyệt" để tránh bị chặn. Cố ý **tắt kiểm
  tra chứng chỉ SSL** vì nhiều cổng thông tin chính thức (.gov.vn) có chứng chỉ hỏng
  — đây là lựa chọn có chủ đích và được ghi log.
- **Module bóc tách (Extractor):** dùng kết hợp **quy tắc regex (ưu tiên) và AI (dự
  phòng)**. Nếu bóc tách bằng quy tắc cho độ tin cậy thấp thì mới gọi AI, giúp tiết
  kiệm chi phí. Ngoài bộ bóc tách tổng quát còn có **các bộ bóc tách chuyên biệt cho
  từng trường** để xử lý đúng cấu trúc trang/PDF riêng.
- **Module chuẩn hóa (Normalizer):** ánh xạ tên ngành, phương thức xét tuyển, tổ hợp
  môn và chỉ tiêu về dạng chuẩn, dựa trên bộ từ điển riêng cho từng trường. Có cả cơ
  chế **suy ra phương thức xét tuyển từ mã tổ hợp** khi nguồn không ghi rõ.
- **Hai trường đã thu thập thành công và đang chạy thật** (mỗi trường 2 nguồn):
  - **Đại học Bách khoa Hà Nội (HUST)** — trang danh sách ngành và trang thông báo
    tuyển sinh 2026.
  - **Đại học Công nghệ - ĐHQGHN (VNU-UET)** — trang web tuyển sinh và file PDF đề
    án; **đã xác nhận phát hiện được mâu thuẫn chỉ tiêu giữa hai nguồn** — chứng minh
    tính năng cốt lõi hoạt động trên dữ liệu thật.
- **Kho tài liệu kiến thức** (phục vụ phân hệ hỏi-đáp ngữ nghĩa) đã có nguồn khai báo
  cho HUST, VNU-UET và NEU, với các đường dẫn đã được cập nhật lại cho đúng (sửa các
  link hỏng trước đây).

**Còn thiếu / chưa hoàn thiện:**
- **Đại học Kinh tế Quốc dân (NEU)** và **Đại học Ngoại thương (FTU):** đã chuẩn bị
  sẵn từ điển ngành/phương thức, nhưng **chưa khai báo nguồn dữ liệu tuyển sinh có
  cấu trúc** (riêng NEU đã có nguồn cho kho kiến thức). Đây là việc còn lại rõ ràng
  nhất để mở rộng độ phủ.
- **Lấy dữ liệu qua trình duyệt giả lập và qua API:** mới có chỗ dành sẵn, hiện vẫn
  quay về cách tải HTTP thông thường.
- **Đọc file Word (.docx):** chưa hiện thực, hiện trả về rỗng.
- **Đọc PDF dạng ảnh quét (OCR):** hệ thống nhận biết được PDF là ảnh quét nhưng
  chưa có khả năng nhận dạng chữ trong ảnh.

### 3.5. Khối dịch vụ nền khác (Inference, Conflict, Tracing)

| Module | Chức năng | Tình trạng |
|--------|-----------|------------|
| **Inference (cổng gọi AI)** | Cổng thống nhất cho mọi lệnh gọi mô hình Gemini, có thử lại, dự phòng sang model nhẹ/nặng khác nhau theo từng tác vụ, và ghi nhận thông số (telemetry). | ✅ Hoàn thành (hiện hỗ trợ nhà cung cấp Gemini) |
| **Pool xoay vòng khóa API** | Quản lý nhiều khóa Gemini, tự xoay vòng và "phạt tạm nghỉ" khóa khi gặp lỗi vượt hạn mức (429) hay lỗi xác thực, đọc cả thời gian chờ do API gợi ý. Bảo đảm an toàn đa luồng. | ✅ Hoàn thành |
| **Conflict (xử lý mâu thuẫn)** | Phát hiện mâu thuẫn, xếp hạng nguồn tất định theo nhiều tiêu chí, gọi AI phân xử khi cần. | ✅ Hoàn thành |
| **Tracing (ghi vết xử lý)** | Ghi lại từng bước xử lý của hệ thống để hiển thị lên bảng theo dõi, kèm thời gian và kết quả từng bước. | ✅ Hoàn thành |

Cổng gọi AI phân biệt rõ **lỗi cứng** (mạng, xác thực, quá hạn) với **lỗi cấu trúc**
(JSON sai định dạng): chỉ thử lại với lỗi cấu trúc, còn lỗi cứng thì dừng và để nơi
gọi xử lý dự phòng. Đây là nền tảng giúp toàn hệ thống suy giảm an toàn.

### 3.6. Khối giao diện web (Web) — ✅ HOÀN THÀNH

- **Máy chủ web (FastAPI)** với các nhóm endpoint: kiểm tra sức khỏe hệ thống, trang
  chat, và API phiên chat (tạo phiên, gửi tin nhắn, lấy trạng thái, lấy vết xử lý).
- **Giao diện chat** bố cục 3 cột linh hoạt: cột trái hiển thị hồ sơ và gợi ý, cột
  giữa là khung chat, cột phải là bảng theo dõi 6 bước xử lý.
- **Các tính năng đã hoàn thiện:** giao diện co giãn theo màn hình (responsive) với
  chế độ ngăn kéo trên di động, chuyển đổi giao diện sáng/tối có nhớ lựa chọn, thông
  báo dạng toast, phím tắt gửi nhanh (Ctrl+Enter), chú ý khả năng truy cập
  (accessibility — nhãn ARIA, vùng cập nhật động cho trình đọc màn hình), thông báo
  bằng tiếng Việt.
- **Bảng theo dõi (Trace panel):** hiển thị tiến trình 6 bước theo thời gian thực
  (giao diện tự hỏi cập nhật), có chế độ debug xem chi tiết kết quả từng bước (bật
  bằng biến môi trường).
- **Luồng chat chạy thông suốt đầu-cuối:** gửi tin nhắn → định tuyến ý định → bóc
  tách/hỏi thêm hồ sơ → chạy tư vấn hoặc hỏi-đáp ở luồng nền → giao diện tự cập nhật
  kết quả khi xong.

**Điểm cần cải thiện (nhỏ):** phần hiển thị debug còn ở dạng JSON thô, chưa trình
bày đẹp; nhưng đây chỉ là công cụ cho lập trình viên, không ảnh hưởng người dùng cuối.

### 3.7. Cơ sở dữ liệu (Database)

- Gồm **14 migration** đánh số tuần tự, có tính idempotent (chạy lại nhiều lần không
  gây lỗi).
- **Bảng cốt lõi** là kho dữ liệu tuyển sinh chuẩn hóa: lưu mỗi bản ghi theo trường
  / ngành / phương thức / năm, kèm chỉ tiêu, tổ hợp môn, hạn nộp, học phí (dạng JSONB
  linh hoạt), cùng nguồn gốc và độ tin cậy. Thiết kế cho phép **cùng một ngành đến
  từ nhiều nguồn được lưu thành các dòng riêng** — nền tảng để phát hiện mâu thuẫn.
- Có đầy đủ bảng cho **phiên chat, tin nhắn, lần chạy tư vấn, vết xử lý, trạng thái
  luồng hội thoại**.
- Có **kho tài liệu kiến thức cho RAG**: bảng tài liệu và bảng đoạn văn bản, trong
  đó cột embedding dùng kiểu **vector** với chỉ mục tìm kiếm gần đúng (HNSW) cho tìm
  kiếm ngữ nghĩa, cùng cơ chế "vân tay nội dung" để khử trùng lặp khi tái thu thập.

**Một điểm nợ kỹ thuật nhỏ cần dọn:** tồn tại song song hai bảng lưu lần chạy tư vấn
— một bảng cũ hiện không còn được code dùng đến, và một bảng mới đang dùng thật. Nên
xóa hoặc làm rõ bảng cũ để tránh nhầm lẫn về sau. Ngoài điểm này, các migration sạch
sẽ, có ràng buộc khóa ngoại và xóa lan truyền hợp lý.

---

## 4. Chất lượng & kiểm thử

- **Bộ kiểm thử (test) đã mở rộng đáng kể:** khoảng **90+ file test** với hàng trăm
  test case, phủ các phần: sáu bước tư vấn, cổng gọi AI (thử lại/dự phòng/xoay vòng
  khóa), logic phát hiện và xử lý mâu thuẫn, vòng đời phiên chat, định tuyến ý định,
  hỏi-đáp kiến thức theo ngữ nghĩa, cắt/nhúng tài liệu (chunk/embedding), các bộ bóc
  tách dữ liệu, và giao diện web.
- **Hạ tầng test trưởng thành:** có sẵn các đối tượng giả lập (fake gateway, fake
  repository, fake dispatcher) để test mà không cần gọi AI thật; test tích hợp/đầu-
  cuối **tự động bỏ qua một cách rõ ràng** khi chưa bật cơ sở dữ liệu Docker, kèm
  hướng dẫn cách bật.
- **Khoảng trống:** chưa có test mô phỏng trình duyệt thật (đang dùng client thử
  nghiệm ở mức HTTP); chưa có test cho hai trường NEU và FTU ở phần dữ liệu có cấu
  trúc (vì chưa có nguồn); chưa có test tải/áp lực.

---

## 5. Mức độ sẵn sàng vận hành & cách cài đặt

- **Cài đặt đã được kịch bản hóa hoàn toàn:** một lệnh khởi tạo lo trọn bộ môi
  trường ảo, thư viện, file cấu hình, cơ sở dữ liệu Docker và chạy migration.
- **Có tài liệu QUICKSTART** hướng dẫn từng bước, kèm chế độ demo dữ liệu giả lập để
  thử nhanh mà không cần dữ liệu thật.
- **Bí mật (khóa API Gemini)** được giữ riêng trong file môi trường, không đưa vào
  mã nguồn. Hệ thống hỗ trợ khai báo **nhiều khóa** để xoay vòng khi gặp giới hạn.

**Đánh giá:** mức độ trưởng thành về cài đặt/triển khai là **cao**.

---

## 6. Tổng hợp: Đã đạt được vs Còn thiếu

### ✅ Đã đạt được
- **Bộ định tuyến ý định** phân loại câu hỏi thành 6 luồng, có giải nghĩa đại từ và
  chuẩn hóa chủ đề, có dự phòng an toàn.
- **Phân hệ hỏi-đáp kiến thức bằng tìm kiếm ngữ nghĩa (vector/pgvector)** chạy thật:
  cắt đoạn, tạo embedding, tìm gần nghĩa, sinh trả lời có trích dẫn, tái dùng
  embedding để tiết kiệm. *(Đây là hạng mục từng được xếp "chưa làm" ở báo cáo trước.)*
- **Luồng hybrid (kết hợp)** chạy song song tư vấn và kiến thức rồi tổng hợp, phục
  vụ các câu hỏi so sánh.
- Toàn bộ **chuỗi tư vấn 6 bước** hoàn chỉnh, Việt hóa, có dự phòng an toàn ở mọi
  điểm gọi AI.
- Tính năng cốt lõi — **phát hiện và xử lý mâu thuẫn dữ liệu** — hoạt động trên dữ
  liệu thật của VNU-UET.
- **Giao diện chat web hoàn thiện**, chạy thông suốt đầu-cuối, có bảng theo dõi xử lý
  thời gian thực, hỗ trợ truy cập (accessibility) và giao diện sáng/tối.
- **Cổng gọi AI** có thử lại/dự phòng, **xoay vòng nhiều khóa API**, ghi nhận thông số.
- **Thu thập dữ liệu thật 2 trường** (HUST, VNU-UET) và **ghi thật vào kho chuẩn hóa**.
- **Cơ sở dữ liệu** 14 migration, hỗ trợ đa nguồn và kho kiến thức vector.
- **Bộ kiểm thử rộng** và **hạ tầng cài đặt trưởng thành**.

### ⚠️ Còn thiếu / cần làm tiếp (ưu tiên cao)
- **Mở rộng độ phủ trường:** khai báo nguồn dữ liệu có cấu trúc cho NEU và FTU (đã
  có từ điển), tiến tới các trường mục tiêu khác.
- **Bổ sung tài liệu kiến thức** cho FTU và mở rộng cho các trường còn lại.
- **Dọn nợ kỹ thuật cơ sở dữ liệu:** xử lý bảng lần-chạy-tư-vấn cũ không còn dùng.
- **Rà lại chất lượng bóc tách** để tránh tín hiệu mâu thuẫn giả ở một số trang.

### ❌ Chưa làm (tính năng nâng cao)
- **Đọc tài liệu nâng cao:** file Word (.docx) và PDF dạng ảnh quét (OCR).
- **Cách lấy dữ liệu nâng cao:** qua trình duyệt giả lập, qua API có xác thực.
- **Vận hành dài hạn:** chưa có cơ chế hết hạn/dọn dẹp phiên chat cũ, chưa có giới
  hạn tần suất gọi theo người dùng, và thông số telemetry mới ghi trong bộ nhớ chứ
  chưa xuất ra hệ thống giám sát bên ngoài.

---

## 7. Đề xuất các bước tiếp theo

1. **Ngắn hạn:** khai báo nguồn và chạy thu thập dữ liệu có cấu trúc cho NEU, FTU để
   tăng nhanh độ phủ; bổ sung nguồn tài liệu kiến thức cho FTU; rà lại các bộ bóc
   tách còn cho tín hiệu mâu thuẫn giả.
2. **Trung hạn:** dọn nợ kỹ thuật cơ sở dữ liệu (bảng lần-chạy cũ); bổ sung test cho
   các trường mới; tinh chỉnh ngưỡng tìm kiếm ngữ nghĩa và chất lượng cắt đoạn để
   nâng độ chính xác hỏi-đáp.
3. **Dài hạn:** bổ sung OCR cho tài liệu ảnh quét và đọc file Word; hiện thực lấy dữ
   liệu qua trình duyệt giả lập/API; chuẩn bị các cơ chế vận hành dài hạn (dọn phiên,
   giới hạn tần suất, xuất telemetry ra hệ thống giám sát).

---

## 8. Kết luận

Dự án đã vượt qua mốc "chạy được đầu-cuối" và bước vào giai đoạn **hoàn thiện chiều
sâu**. Ba phân hệ then chốt — **định tuyến hội thoại đa luồng**, **hỏi-đáp kiến thức
theo ngữ nghĩa (RAG/vector)**, và **tư vấn nhận biết mâu thuẫn** — đều đã hoạt động
thật, có dự phòng an toàn và được kiểm thử. Rào cản lớn nhất còn lại **không nằm ở
năng lực kỹ thuật của hệ thống mà ở độ phủ dữ liệu**: cần khai báo thêm nguồn cho các
trường mục tiêu. Đây là công việc vận hành/cấu hình rõ ràng, không phải bài toán
nghiên cứu, nên lộ trình mở rộng là khả thi và có thể ước lượng được.
