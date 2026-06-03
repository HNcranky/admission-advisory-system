BÁO CÁO TIẾN ĐỘ DỰ ÁN ADVISORY AGENT

1\. Xây dựng kiến trúc tổng thể của hệ thống

* Hệ thống đã được thiết kế theo hướng phân tách thành hai lớp chính:  
  * agents: chịu trách nhiệm điều phối luồng xử lý.  
  * services: chịu trách nhiệm thực hiện logic nghiệp vụ.  
* Kiến trúc này giúp tăng khả năng mở rộng, bảo trì và kiểm thử độc lập từng thành phần.  
* Luồng xử lý tổng thể đã được xác định rõ ràng theo pipeline:  
* Phân tích hồ sơ người dùng.  
* Truy xuất dữ liệu chương trình phù hợp.  
* Suy luận và xếp hạng kết quả.  
* Kiểm tra ràng buộc chính sách.  
* Sinh câu trả lời cuối cùng.

2\. Thiết kế và chuẩn hóa mô hình dữ liệu

* Các model dữ liệu được xây dựng bằng Pydantic  
* Các thực thể chính đã được định nghĩa gồm:  
  * StudentProfile: lưu thông tin hồ sơ học sinh.  
  * Evidence: lưu nguồn chứng cứ và mức độ tin cậy.  
  * CandidateProgram: biểu diễn chương trình đào tạo được truy xuất.  
  * EligibilityCheck: lưu kết quả đánh giá điều kiện phù hợp.  
  * RankedRecommendation: lưu danh sách khuyến nghị đã được xếp hạng.  
  * PolicyDecision: lưu kết quả kiểm tra các ràng buộc chính sách.  
* AgentState để quản lý trạng thái chung xuyên suốt toàn bộ pipeline.

3\. Thiết kế các agent trong hệ thống

3.1. profile\_agent

* Đã xây dựng agent có nhiệm vụ phân tích truy vấn người dùng.  
* Có khả năng trích xuất các thông tin quan trọng từ câu hỏi tự nhiên như:  
  * điểm số,  
  * tổ hợp môn,  
  * ngành học ưu tiên,  
  * trường học ưu tiên.  
* Có khả năng xác định các trường thông tin còn thiếu để hỗ trợ bước hỏi bổ sung sau này.

3.2. retrieval\_agent

* Đã xây dựng agent phục vụ truy xuất dữ liệu từ nguồn lưu trữ chuẩn hóa.  
* Có khả năng:  
  * tạo bộ lọc tìm kiếm từ hồ sơ người dùng,  
  * gọi hàm truy xuất danh sách chương trình phù hợp,  
  * lọc lại kết quả theo tổ hợp môn,  
  * ghi nhận lỗi truy xuất nếu xảy ra,  
  * phát hiện xung đột dữ liệu ban đầu.

3.3. reasoning\_agent

* Đã xây dựng agent thực hiện suy luận trên danh sách chương trình đã truy xuất.  
* Agent này có nhiệm vụ:  
  * đánh giá mức độ phù hợp của từng chương trình,  
  * sinh kết quả kiểm tra điều kiện,  
  * xếp hạng các chương trình theo mức độ phù hợp.

3.4. policy\_agent

* Đã xây dựng agent để kiểm soát các ràng buộc an toàn và chính sách phản hồi.  
* Agent này đảm nhiệm:  
  * kiểm tra dữ liệu hồ sơ có bị thiếu hay không,  
  * kiểm tra dữ liệu truy xuất có đủ bằng chứng không,  
  * lọc bỏ các khuyến nghị thiếu nguồn tham chiếu,  
  * chặn các kết luận quá mức chắc chắn.

3.5. explanation\_agent

* Đã xây dựng agent để tổng hợp kết quả cuối cùng cho người dùng.  
* Agent này có nhiệm vụ:  
  * tổng hợp hồ sơ đã phân tích,  
  * hiển thị các chương trình được đề xuất,  
  * nêu lý do và lưu ý cho từng đề xuất,  
  * đính kèm nguồn tham chiếu,  
  * bổ sung cảnh báo và thông tin cần hỏi thêm nếu cần.

3.6. conflict\_agent

* Đã tách riêng agent phục vụ phát hiện và hợp nhất các conflict trong dữ liệu.

3.7. advisory\_agent

* Đã duy trì một wrapper tương thích ngược cho các luồng gọi cũ.  
* Điều này giúp đảm bảo hệ thống vẫn hoạt động ổn định trong quá trình tái cấu trúc.

4\. Xây dựng lớp service nghiệp vụ

4.1. profile\_service

* Đã xây dựng các hàm phục vụ phân tích hồ sơ người dùng.  
* Các chức năng đã có gồm:  
  * chuẩn hóa văn bản tiếng Việt sang dạng dễ xử lý,  
  * đọc dữ liệu từ các dictionary chuẩn hóa,  
  * trích xuất điểm số từ câu truy vấn,  
  * trích xuất tổ hợp môn,  
  * nhận diện ngành học mong muốn,  
  * nhận diện trường học mong muốn,  
  * tạo hồ sơ người dùng hoàn chỉnh ở dạng cấu trúc.

4.2. retrieval\_service

* Đã xây dựng các hàm phục vụ truy xuất dữ liệu tuyển sinh.  
* Các chức năng đã có gồm:  
  * xây dựng filter từ hồ sơ người dùng,  
  * truy vấn dữ liệu từ bảng PostgreSQL,  
  * gắn bằng chứng nguồn dữ liệu,  
  * phát hiện xung đột giữa các bản ghi.

4.3. reasoning\_service

* Đã xây dựng logic suy luận dựa trên luật để đánh giá mức độ phù hợp.  
* Các tiêu chí đánh giá đã được đưa vào gồm:  
  * mức độ phù hợp của tổ hợp môn,  
  * mức độ khớp với ngành ưu tiên,  
  * mức độ khớp với trường ưu tiên,  
  * khoảng điểm của thí sinh.

4.4. policy\_service

* Đã xây dựng lớp kiểm soát chính sách phản hồi.  
* Hệ thống hiện có khả năng:  
  * chặn các phát ngôn mang tính cam kết chắc chắn,  
  * cảnh báo khi hồ sơ thiếu dữ liệu quan trọng,  
  * cảnh báo khi phát hiện xung đột dữ liệu,  
  * cảnh báo khi không tìm thấy chương trình phù hợp,  
  * loại bỏ các recommendation không có bằng chứng nguồn.

4.5. explanation\_service

* Đã xây dựng logic sinh câu trả lời cuối cùng theo hướng có giải thích.  
* Nội dung phản hồi hiện có thể bao gồm:  
  * tóm tắt hồ sơ người dùng,  
  * danh sách chương trình được gợi ý,  
  * lý do lựa chọn,  
  * lưu ý cần quan tâm,  
  * nguồn tham chiếu,  
  * cảnh báo và yêu cầu bổ sung thông tin.

5\. Hoàn thiện luồng orchestration bằng graph

* Đã xây dựng graph xử lý sử dụng LangGraph.  
* Các node đã được kết nối theo thứ tự:  
  * profile  
  * retrieve  
  * reason  
  * policy  
  * explain

6\. Kết quả đạt được đến thời điểm hiện tại

* Đã hình thành được khung kiến trúc hoàn chỉnh cho hệ thống tư vấn tuyển sinh theo hướng agent-based.  
* Đã chuẩn hóa dữ liệu đầu vào, dữ liệu trung gian và dữ liệu đầu ra.  
* Đã bổ sung cơ chế cảnh báo, kiểm soát chính sách và nguồn tham chiếu.

7\. Hạn chế hiện tại

* Cơ chế suy luận hiện vẫn chủ yếu dựa trên rule-based scoring, chưa kết hợp mô hình học máy hoặc LLM reasoning nâng cao.  
* Khả năng truy xuất hiện phụ thuộc vào dữ liệu chuẩn hóa sẵn có trong cơ sở dữ liệu.  
* Khả năng cá nhân hóa còn hạn chế.

8\. Hướng phát triển tiếp theo

* Hoàn thiện môi trường để chạy và xây dựng bộ test để chạy thử nghiệm.  
* Mở rộng dữ liệu tuyển sinh và cải thiện chất lượng retrieval.  
* Nâng cấp cơ chế suy luận, đưa vào sử dụng một số mô hình opensource như Qwen3.5-4B, Ministral-3-3B.

