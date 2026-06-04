## Các edge case hệ thống tư vấn tuyển sinh nên xử lý được

Dựa trên use case lý tưởng trước đó, hệ thống không chỉ cần xử lý luồng thuận như “hỏi điểm → hỏi tổ hợp → đề xuất trường”, mà còn phải xử lý các tình huống người dùng trả lời thiếu, sửa thông tin, đưa dữ liệu mâu thuẫn hoặc hệ thống không đủ căn cứ để kết luận.

Dưới đây là các edge case quan trọng, có thể dùng trực tiếp để viết test scenario hoặc acceptance criteria.

---

# Nhóm 1 — Edge case khi thu thập profile

## EC-01: Người dùng trả lời cực ngắn theo câu hỏi đang chờ

### Context

```json
{
  "pending_slot": "admission_year"
}
```

### Hội thoại

```text
Agent: Em đang xét tuyển cho năm nào?
User: 2026
```

### Hành vi mong muốn

Hệ thống phải hiểu `2026` là năm xét tuyển, không coi đây là message mơ hồ hoặc intent mới.

### State mong muốn

```json
{
  "admission_year": 2026
}
```

### Không được xảy ra

* Không hỏi lại “Em đang xét tuyển cho năm nào?”.
* Không chuyển sang câu trả lời chung chung.
* Không chạy retrieval trước khi đủ dữ liệu.
* Không cần gọi intent router cho câu trả lời slot đơn giản.

### Acceptance Criteria

**Given** `pending_slot = admission_year`
**When** người dùng gửi `"2026"`
**Then** hệ thống cập nhật `admission_year = 2026`
**And** chuyển sang hỏi slot cần thiết tiếp theo.

---

## EC-02: Người dùng trả lời không đúng slot đang được hỏi nhưng cung cấp thông tin hợp lệ khác

### Context

```json
{
  "pending_slot": "subject_combination"
}
```

### Hội thoại

```text
Agent: Em xét tuyển theo tổ hợp nào?
User: Em chỉ muốn học ở Hà Nội thôi.
```

### Hành vi mong muốn

Hệ thống không được bỏ qua thông tin `Hà Nội`. Nó cần:

1. Cập nhật `location_preference = "Ha Noi"`.
2. Nhận biết rằng `subject_combination` vẫn còn thiếu.
3. Hỏi lại về tổ hợp xét tuyển.

### Response mong muốn

> Mình đã ghi nhận em ưu tiên học ở Hà Nội. Em xét tuyển theo tổ hợp nào, ví dụ A00, A01 hoặc D01?

### Acceptance Criteria

**Given** hệ thống đang chờ `subject_combination`
**When** người dùng cung cấp `location_preference` thay vì tổ hợp
**Then** hệ thống vẫn lưu địa điểm
**And** giữ `subject_combination` là slot còn thiếu
**And** tiếp tục hỏi tổ hợp.

---

## EC-03: Một câu trả lời chứa nhiều slot cùng lúc

### Context

Hệ thống đang hỏi về điểm.

### Hội thoại

```text
Agent: Điểm thi dự kiến của em khoảng bao nhiêu?
User: Em được khoảng 26.5 điểm A01, muốn học CNTT ở Hà Nội.
```

### State mong muốn

```json
{
  "total_score": 26.5,
  "subject_combination": "A01",
  "explicit_preferred_majors": [
    "information_technology"
  ],
  "location_preference": "Ha Noi"
}
```

### Hành vi mong muốn

Hệ thống phải cập nhật tất cả thông tin có giá trị trong một lượt, không chỉ lấy `total_score` vì đó là slot đang hỏi.

### Không được xảy ra

* Bỏ qua `A01`, ngành hoặc địa điểm.
* Hỏi lại các thông tin người dùng vừa cung cấp.
* Ghi đè profile bằng các field rỗng.

### Acceptance Criteria

**When** một message chứa nhiều thông tin hồ sơ hợp lệ
**Then** hệ thống phải tạo nhiều update operations trong cùng một turn
**And** chỉ hỏi slot còn thiếu thật sự.

---

## EC-04: Người dùng cung cấp dữ liệu không hợp lệ

### Hội thoại

```text
Agent: Tổng điểm xét tuyển của em là bao nhiêu?
User: Em được 35 điểm theo thang 30.
```

### Hành vi mong muốn

Nếu phương thức hiện tại là điểm thi THPT thang 30, hệ thống không được lưu `total_score = 35`.

### Response mong muốn

> Với phương thức xét điểm thi THPT theo thang 30, tổng điểm 35 chưa hợp lệ. Em kiểm tra lại điểm hoặc cho mình biết em đang dùng phương thức xét tuyển nào nhé.

### Acceptance Criteria

**Given** `admission_method = national_exam_score` và thang điểm tối đa là 30
**When** người dùng nhập `total_score = 35`
**Then** hệ thống không cập nhật điểm vào profile chính thức
**And** yêu cầu người dùng kiểm tra hoặc làm rõ phương thức xét tuyển.

---

# Nhóm 2 — Edge case về sửa đổi profile

## EC-05: Người dùng sửa lại điểm sau khi hệ thống đã đưa khuyến nghị

### State trước đó

```json
{
  "total_score": 27.0,
  "subject_combination": "A01",
  "explicit_preferred_majors": [
    "computer_science"
  ]
}
```

### Hội thoại

```text
User: Em nhầm, điểm của em chỉ là 25.75 chứ không phải 27.
```

### State mong muốn

```json
{
  "total_score": 25.75
}
```

### Hành vi mong muốn

Hệ thống phải:

1. Thay thế điểm cũ, không giữ đồng thời hai giá trị.
2. Đánh dấu đây là correction.
3. Chạy lại đánh giá/ranking dựa trên điểm mới.
4. Không tiếp tục trình bày khuyến nghị cũ như còn hợp lệ.

### Response mong muốn

> Mình đã cập nhật điểm dự kiến của em từ 27 xuống 25.75. Vì điểm thay đổi, danh sách lựa chọn phù hợp cũng cần được đánh giá lại.

### Acceptance Criteria

**Given** kết quả tư vấn trước đó được tính với `total_score = 27.0`
**When** người dùng sửa điểm thành `25.75`
**Then** mọi đánh giá phụ thuộc vào điểm phải được invalidated hoặc tính lại
**And** response mới phải dùng điểm `25.75`.

---

## EC-06: Người dùng muốn thêm ngành, không thay thế ngành cũ

### State trước đó

```json
{
  "explicit_preferred_majors": [
    "computer_science"
  ]
}
```

### Hội thoại

```text
User: Em muốn xem thêm cả ngành Khoa học dữ liệu nữa.
```

### State mong muốn

```json
{
  "explicit_preferred_majors": [
    "computer_science",
    "data_science"
  ]
}
```

### Không được xảy ra

```json
{
  "explicit_preferred_majors": [
    "data_science"
  ]
}
```

### Acceptance Criteria

**Given** profile đã có một ngành ưu tiên
**When** người dùng dùng từ `"thêm"`, `"cả"` hoặc `"xem thêm"` để nói về ngành khác
**Then** hệ thống phải append ngành mới
**And** không ghi đè ngành cũ.

---

## EC-07: Người dùng muốn bỏ một ngành khỏi danh sách

### State trước đó

```json
{
  "explicit_preferred_majors": [
    "computer_science",
    "data_science",
    "artificial_intelligence"
  ]
}
```

### Hội thoại

```text
User: Bỏ ngành AI đi, em chỉ muốn xem Khoa học máy tính với Khoa học dữ liệu.
```

### State mong muốn

```json
{
  "explicit_preferred_majors": [
    "computer_science",
    "data_science"
  ]
}
```

### Hành vi mong muốn

Hệ thống phải hiểu đây là thao tác `remove`, không phải một lượt extract ngành mới rồi làm mất context trước đó.

### Acceptance Criteria

**When** người dùng yêu cầu bỏ một lựa chọn đã có
**Then** hệ thống xoá đúng lựa chọn đó khỏi state
**And** chạy lại retrieval/ranking nếu danh sách kết quả phụ thuộc vào ngành bị bỏ.

---

## EC-08: Người dùng thay đổi constraint từ chặt sang rộng hơn

### State trước đó

```json
{
  "location_preference": "Ha Noi"
}
```

### Hội thoại

```text
User: Nếu có trường tốt hơn thì học ở Hải Phòng hoặc các tỉnh miền Bắc cũng được.
```

### State mong muốn

```json
{
  "location_preference": {
    "preferred": [
      "Ha Noi",
      "Hai Phong",
      "Mien Bac"
    ],
    "strict": false
  }
}
```

### Điểm quan trọng

Không phải preference nào cũng là filter tuyệt đối. Trong câu này, Hà Nội không còn là điều kiện bắt buộc; nó trở thành ưu tiên mềm.

### Acceptance Criteria

**When** người dùng nới điều kiện địa điểm
**Then** hệ thống phải mở rộng search space
**And** không loại bỏ chương trình tốt chỉ vì ngoài Hà Nội
**And** vẫn có thể ưu tiên Hà Nội khi xếp hạng.

---

# Nhóm 3 — Edge case về ngành và ý định người dùng

## EC-09: Người dùng nói sở thích, chưa chọn ngành cụ thể

### Hội thoại

```text
User: Em thích code, thích làm app với học AI.
```

### State mong muốn

```json
{
  "inferred_interest_tags": [
    "software_development",
    "mobile_development",
    "artificial_intelligence"
  ],
  "explicit_preferred_majors": []
}
```

### Hành vi mong muốn

Hệ thống có thể gợi ý các nhóm ngành phù hợp, nhưng không được coi người dùng đã xác nhận chọn một ngành cụ thể.

### Response mong muốn

> Với sở thích lập trình ứng dụng và AI, em có thể cân nhắc Kỹ thuật phần mềm, Khoa học máy tính, Công nghệ thông tin hoặc Khoa học dữ liệu. Em muốn ưu tiên hướng nào hơn?

### Acceptance Criteria

**Given** người dùng chỉ mô tả sở thích hoặc nghề nghiệp mong muốn
**Then** hệ thống cập nhật interest tags
**And** chưa ghi các ngành suy luận thành lựa chọn đã xác nhận.

---

## EC-10: Từ khoá ngắn gây match nhầm ngành

### Hội thoại

```text
User: Em muốn học tài chính ngân hàng.
```

### Rủi ro

Nếu hệ thống match substring `"ai"` trong `"tài chính"`, nó có thể suy luận nhầm sang Artificial Intelligence. Đây là nguy cơ trực tiếp từ cách map keyword bằng substring trong service hiện tại. 

### State mong muốn

```json
{
  "explicit_preferred_majors": [
    "finance_banking"
  ],
  "inferred_interest_tags": []
}
```

### Không được xảy ra

```json
{
  "explicit_preferred_majors": [
    "finance_banking",
    "artificial_intelligence",
    "data_science"
  ]
}
```

### Acceptance Criteria

**When** người dùng đề cập `"tài chính"`
**Then** token `"ai"` bên trong từ `"tài"` không được map sang Artificial Intelligence
**And** keyword mapping phải dùng exact token hoặc phrase boundary.

---

## EC-11: Người dùng nhập ngành chưa tồn tại trong taxonomy

### Hội thoại

```text
User: Em muốn học Digital Marketing.
```

### Hành vi mong muốn

Nếu taxonomy chưa có canonical ID tương ứng, hệ thống không được làm mất dữ liệu người dùng đã cung cấp.

### State mong muốn

```json
{
  "explicit_preferred_majors": [],
  "unresolved_major_mentions": [
    "Digital Marketing"
  ]
}
```

### Response mong muốn

> Mình đã ghi nhận em quan tâm Digital Marketing. Hiện mình cần đối chiếu tên ngành/chương trình tương ứng trong dữ liệu tuyển sinh để lọc chính xác hơn.

### Acceptance Criteria

**When** ngành được nhắc tới chưa map được sang canonical ID
**Then** hệ thống lưu nguyên văn mention ở trạng thái unresolved
**And** không âm thầm bỏ qua ngành đó.

---

# Nhóm 4 — Edge case về điểm và điều kiện xét tuyển

## EC-12: Điểm cao nhưng sai tổ hợp xét tuyển

### Profile người dùng

```json
{
  "admission_year": 2026,
  "admission_method": "national_exam_score",
  "total_score": 28.0,
  "subject_combination": "D01"
}
```

### Chương trình

```json
{
  "program": "Khoa học máy tính",
  "accepted_combinations": [
    "A00",
    "A01"
  ],
  "reference_cutoff": 26.5
}
```

### Hành vi mong muốn

Dù điểm `28.0 > 26.5`, hệ thống không được xếp chương trình này là phù hợp theo khả năng trúng tuyển, vì thí sinh không có tổ hợp hợp lệ.

### Kết quả mong muốn

```json
{
  "eligible": false,
  "score_fit": null,
  "recommendation_level": "NOT_ELIGIBLE",
  "reason": "Chương trình không hỗ trợ tổ hợp D01 theo phương thức đã chọn."
}
```

### Acceptance Criteria

**Given** điểm thí sinh cao hơn điểm tham chiếu
**But** tổ hợp không được chấp nhận
**Then** kết quả phải là `NOT_ELIGIBLE`
**And** không hiển thị như một lựa chọn an toàn.

---

## EC-13: Điểm được cung cấp nhưng chưa biết phương thức xét tuyển

### Hội thoại

```text
User: Em được 27 điểm.
```

### Vấn đề

`27 điểm` có thể là:

* điểm thi tốt nghiệp THPT;
* điểm học bạ quy đổi;
* điểm đánh giá năng lực quy đổi;
* điểm theo công thức xét tuyển riêng.

### Hành vi mong muốn

Hệ thống lưu được điểm tạm thời nhưng chưa dùng điểm đó để so sánh với cutoff của một phương thức cụ thể nếu chưa biết `admission_method`.

### State mong muốn

```json
{
  "total_score": 27.0,
  "admission_method": null
}
```

### Response mong muốn

> Em dự kiến được 27 điểm theo phương thức nào: điểm thi tốt nghiệp THPT, học bạ, đánh giá năng lực hay phương thức kết hợp?

### Acceptance Criteria

**Given** có `total_score` nhưng thiếu `admission_method`
**Then** hệ thống không được đánh giá score fit chính thức
**And** phải hỏi phương thức xét tuyển.

---

## EC-14: Điểm sát ngưỡng, hệ thống không được khẳng định chắc chắn

### Profile người dùng

```json
{
  "total_score": 26.25,
  "subject_combination": "A01",
  "admission_method": "national_exam_score"
}
```

### Dữ liệu tham chiếu

```json
{
  "reference_year": 2025,
  "cutoff_score": 26.20
}
```

### Hành vi mong muốn

Hệ thống không được nói:

> Em đủ điểm đỗ ngành này.

Vì chênh lệch chỉ là `+0.05` và cutoff năm 2026 chưa có.

### Response mong muốn

> Điểm dự kiến của em gần tương đương mức tham chiếu năm 2025, chỉ cao hơn 0.05 điểm. Đây là lựa chọn sát ngưỡng và có rủi ro, chưa thể kết luận khả năng trúng tuyển năm 2026.

### Acceptance Criteria

**When** điểm người dùng nằm trong biên sát cutoff tham chiếu
**Then** hệ thống gắn nhãn `BORDERLINE` hoặc tương đương
**And** không dùng ngôn ngữ khẳng định trúng tuyển.

---

## EC-15: Điểm cao hơn cutoff năm gần nhất nhưng chương trình biến động mạnh qua các năm

### Dữ liệu

```json
{
  "candidate_score": 26.4,
  "historical_cutoffs": {
    "2023": 24.8,
    "2024": 26.7,
    "2025": 25.9
  }
}
```

### Hành vi mong muốn

Nếu chỉ so với năm 2025:

```text
26.4 - 25.9 = +0.5
```

hệ thống có thể đánh giá quá lạc quan.

### Kết quả mong muốn

```json
{
  "score_fit": "UNCERTAIN",
  "reason": "Điểm chuẩn chương trình biến động đáng kể qua các năm gần nhất."
}
```

### Acceptance Criteria

**Given** điểm chuẩn lịch sử biến động vượt ngưỡng hệ thống quy định
**When** đánh giá mức phù hợp
**Then** hệ thống phải giảm độ chắc chắn của recommendation
**And** hiển thị cảnh báo biến động dữ liệu lịch sử.

---

# Nhóm 5 — Edge case về dữ liệu nguồn và conflict-aware advisory

## EC-16: Hai nguồn chính thức ghi khác nhau về điểm chuẩn

### Dữ liệu truy xuất

```json
[
  {
    "source": "school_official_site",
    "cutoff_score": 26.2
  },
  {
    "source": "parent_university_portal",
    "cutoff_score": 26.8
  }
]
```

### Profile người dùng

```json
{
  "total_score": 26.5
}
```

### Hành vi mong muốn

Kết luận thay đổi theo nguồn:

| Nguồn            | Chênh lệch | Nhận định  |
| ---------------- | ---------: | ---------- |
| Nguồn trường     |     `+0.3` | Cạnh tranh |
| Nguồn đại học mẹ |     `-0.3` | Thử sức    |

Hệ thống không được âm thầm chọn một nguồn để đưa ra kết luận dứt khoát.

### Response mong muốn

> Hiện có mâu thuẫn giữa hai nguồn về điểm tham chiếu của chương trình: một nguồn ghi 26.2, nguồn còn lại ghi 26.8. Với điểm 26.5, kết luận thay đổi tùy nguồn, vì vậy lựa chọn này nên được xem là cạnh tranh/thử sức cho đến khi có công bố được xác nhận.

### Acceptance Criteria

**Given** hai nguồn đáng tin cậy có giá trị cutoff khác nhau đủ làm thay đổi nhãn recommendation
**Then** hệ thống phải gắn cờ conflict
**And** hiển thị cả hai giá trị cùng nguồn tương ứng
**And** không trả về một nhãn chắc chắn duy nhất.

---

## EC-17: Nguồn ghi khác nhau về chỉ tiêu nhưng không ảnh hưởng điều kiện xét tuyển trực tiếp

### Dữ liệu

```json
[
  {
    "source": "source_a",
    "quota": 120
  },
  {
    "source": "source_b",
    "quota": 150
  }
]
```

### Hành vi mong muốn

Hệ thống vẫn có thể đề xuất chương trình nếu tổ hợp, ngành và điểm phù hợp; tuy nhiên phải cảnh báo rằng chỉ tiêu chưa thống nhất, vì nó ảnh hưởng mức cạnh tranh.

### Response mong muốn

> Chương trình phù hợp với hồ sơ hiện tại của em. Tuy nhiên, số chỉ tiêu đang được hai nguồn công bố khác nhau là 120 và 150, nên mức cạnh tranh thực tế có thể thay đổi.

### Acceptance Criteria

**Given** conflict nằm ở quota nhưng eligibility không bị thay đổi
**Then** chương trình vẫn có thể xuất hiện trong danh sách đề xuất
**And** phải hiển thị cảnh báo ảnh hưởng đến độ chắc chắn của ranking.

---

## EC-18: Không có dữ liệu đúng năm người dùng xét tuyển

### Profile

```json
{
  "admission_year": 2026
}
```

### Dữ liệu hiện có

```json
{
  "latest_available_admission_year": 2025
}
```

### Hành vi mong muốn

Hệ thống có thể dùng năm 2025 làm tham chiếu, nhưng phải nói rõ đây không phải dữ liệu chính thức cho năm 2026.

### Response mong muốn

> Chưa có điểm chuẩn chính thức cho kỳ tuyển sinh năm 2026 trong dữ liệu hiện tại. Đánh giá dưới đây sử dụng dữ liệu năm 2025 làm tham chiếu và có thể thay đổi khi trường công bố thông tin mới.

### Acceptance Criteria

**When** không có dữ liệu của đúng `admission_year`
**Then** hệ thống chỉ được trả về đánh giá tham khảo
**And** phải hiển thị `reference_year`
**And** không khẳng định kết quả trúng tuyển.

---

# Nhóm 6 — Edge case về ngân sách và preference

## EC-19: Trường rất phù hợp về điểm/ngành nhưng vượt ngân sách

### Profile

```json
{
  "total_score": 27.0,
  "preferred_majors": [
    "data_science"
  ],
  "tuition_budget": {
    "maximum": 40000000,
    "period": "year"
  }
}
```

### Chương trình

```json
{
  "program": "Khoa học dữ liệu",
  "score_fit": "SAFER",
  "tuition_per_year": 65000000
}
```

### Hành vi mong muốn

Hệ thống không được xếp chương trình này thành lựa chọn tối ưu mà không cảnh báo.

### Kết quả mong muốn

```json
{
  "academic_fit": "HIGH",
  "score_fit": "SAFER",
  "tuition_fit": "NOT_FIT",
  "recommendation_level": "CONSIDER_WITH_FINANCIAL_CONCERN"
}
```

### Response mong muốn

> Chương trình này phù hợp cao về ngành và mức điểm, nhưng học phí khoảng 65 triệu/năm, vượt ngân sách 40 triệu/năm của em. Đây chỉ nên là lựa chọn cân nhắc nếu em có phương án học bổng hoặc điều chỉnh ngân sách.

### Acceptance Criteria

**When** chương trình phù hợp học thuật nhưng vượt ngân sách
**Then** hệ thống không được gắn nhãn an toàn tổng thể
**And** phải giải thích rõ xung đột giữa academic fit và financial fit.

---

## EC-20: Người dùng nói ngân sách không phải điều kiện bắt buộc

### Hội thoại

```text
User: Em muốn học phí dưới 40 triệu, nhưng nếu ngành thực sự tốt thì cao hơn một chút cũng cân nhắc được.
```

### State mong muốn

```json
{
  "tuition_budget": {
    "preferred_maximum": 40000000,
    "strict": false
  }
}
```

### Hành vi mong muốn

Chương trình vượt nhẹ ngân sách vẫn có thể được đưa vào danh sách, nhưng phải xếp sau các lựa chọn đáp ứng ngân sách hoặc đánh dấu cần cân nhắc.

### Acceptance Criteria

**Given** ngân sách là soft preference
**Then** hệ thống không được loại tuyệt đối chương trình vượt ngân sách
**And** phải phản ánh mức vượt ngân sách trong explanation/ranking.

---

# Nhóm 7 — Edge case về điều khiển hội thoại

## EC-21: Người dùng muốn dừng advisory giữa luồng

### Context

```json
{
  "pending_slot": "subject_combination",
  "advisory_active": true
}
```

### Hội thoại

```text
Agent: Em xét tuyển theo tổ hợp nào?
User: Thôi, em muốn hỏi về học phí của UET trước.
```

### Hành vi mong muốn

Hệ thống phải nhận biết người dùng đang đổi mục tiêu, không cố parse `"học phí của UET"` thành câu trả lời cho `subject_combination`.

### Response mong muốn

> Được, mình sẽ chuyển sang thông tin học phí của UET. Hồ sơ tư vấn đang thu thập có thể được giữ lại để em tiếp tục sau.

### Acceptance Criteria

**When** người dùng rõ ràng chuyển chủ đề trong lúc đang có pending slot
**Then** hệ thống không được cưỡng ép message vào slot đang chờ
**And** phải chuyển intent hoặc tạm dừng flow phù hợp.

---

## EC-22: Người dùng yêu cầu bắt đầu lại hồ sơ

### State trước đó

```json
{
  "admission_year": 2026,
  "total_score": 27.0,
  "subject_combination": "A01",
  "preferred_majors": [
    "computer_science"
  ]
}
```

### Hội thoại

```text
User: Xoá thông tin cũ đi, em muốn tư vấn lại từ đầu cho em gái em.
```

### Hành vi mong muốn

Hệ thống không được tiếp tục dùng hồ sơ cũ cho người mới.

### Response mong muốn

> Mình đã bắt đầu một hồ sơ tư vấn mới. Em gái bạn đang xét tuyển cho năm nào?

### Acceptance Criteria

**When** người dùng yêu cầu reset hoặc chuyển sang tư vấn cho người khác
**Then** profile hiện tại phải được xoá khỏi active advisory state
**And** retrieval sau đó không được sử dụng dữ liệu hồ sơ cũ.

---

## EC-23: Người dùng hỏi “tại sao đề xuất này thay đổi?”

### Context

Người dùng đã sửa điểm từ `27.0` xuống `25.75`, ranking thay đổi.

### Hội thoại

```text
User: Tại sao lúc trước bạn đề xuất UET, giờ lại ưu tiên PTIT?
```

### Hành vi mong muốn

Hệ thống phải giải thích dựa trên thay đổi profile, không trả lời chung chung.

### Response mong muốn

> Trước đó mình đánh giá dựa trên điểm dự kiến 27.0. Sau khi em cập nhật còn 25.75, khoảng cách với mức điểm tham chiếu của UET giảm đáng kể, nên UET chuyển thành lựa chọn thử sức hơn. PTIT hiện phù hợp hơn về khả năng cạnh tranh và vẫn đáp ứng ngành, địa điểm và ngân sách của em.

### Acceptance Criteria

**Given** ranking thay đổi sau một profile correction
**When** người dùng hỏi lý do
**Then** hệ thống phải truy được field thay đổi ảnh hưởng đến recommendation
**And** giải thích bằng dữ liệu trước/sau.

---

# Nhóm 8 — Edge case về độ tin cậy và an toàn tư vấn

## EC-24: Không tìm được chương trình đáp ứng toàn bộ điều kiện

### Profile

```json
{
  "total_score": 23.0,
  "subject_combination": "A01",
  "preferred_majors": [
    "artificial_intelligence"
  ],
  "location_preference": "Ha Noi",
  "tuition_budget": {
    "maximum": 20000000,
    "strict": true
  }
}
```

### Hành vi mong muốn

Hệ thống không được bịa ra kết quả phù hợp hoàn toàn.

### Response mong muốn

> Mình chưa tìm thấy chương trình đáp ứng đồng thời ngành AI, khu vực Hà Nội, mức điểm tham khảo và ngân sách dưới 20 triệu/năm trong dữ liệu hiện có. Em có thể cân nhắc nới một trong ba tiêu chí: ngành gần với AI, khu vực học hoặc ngân sách.

### Acceptance Criteria

**When** không có kết quả thỏa toàn bộ hard constraints
**Then** hệ thống phải trả về `NO_EXACT_MATCH`
**And** chỉ đề xuất mở rộng điều kiện một cách minh bạch
**And** không tự động nới constraint khi chưa thông báo.

---

## EC-25: Dữ liệu thiếu học phí nhưng hệ thống vẫn phải xếp hạng có điều kiện

### Chương trình

```json
{
  "program": "Khoa học máy tính",
  "score_fit": "COMPETITIVE",
  "tuition_per_year": null
}
```

### Hành vi mong muốn

Không được tự suy luận `tuition_fit = HIGH` chỉ vì không thấy học phí.

### Kết quả mong muốn

```json
{
  "score_fit": "COMPETITIVE",
  "tuition_fit": "UNKNOWN",
  "recommendation_level": "RECOMMENDED_WITH_MISSING_TUITION_DATA"
}
```

### Response mong muốn

> Chương trình phù hợp về ngành, tổ hợp và mức điểm tham chiếu. Tuy nhiên, mình chưa có dữ liệu học phí đủ tin cậy để xác nhận chương trình nằm trong ngân sách của em.

### Acceptance Criteria

**When** thiếu dữ liệu cho một preference quan trọng
**Then** hệ thống phải đánh dấu giá trị đó là `UNKNOWN`
**And** không coi thiếu dữ liệu là điều kiện đã đạt.

---

# Danh sách edge case ưu tiên để triển khai test trước

Nếu bạn chỉ có thời gian implement một bộ test quan trọng cho bản demo, nên ưu tiên 12 case sau:

| Ưu tiên | Edge case                                       | Vì sao quan trọng                                |
| ------: | ----------------------------------------------- | ------------------------------------------------ |
|       1 | EC-01: Trả lời ngắn `"2026"` theo pending slot  | Bắt đúng bug `admission_year` hiện tại           |
|       2 | EC-03: Một câu chứa nhiều slot                  | Rất thường gặp trong hội thoại thật              |
|       3 | EC-05: Sửa điểm sau recommendation              | Kiểm tra patch + re-ranking                      |
|       4 | EC-06: Thêm ngành không ghi đè ngành cũ         | Bắt lỗi merge list                               |
|       5 | EC-10: `"tài chính"` không bị match nhầm `"AI"` | Bắt lỗi mapping substring                        |
|       6 | EC-12: Điểm cao nhưng sai tổ hợp                | Tránh tư vấn sai nghiệp vụ                       |
|       7 | EC-13: Có điểm nhưng chưa biết phương thức      | Tránh so sánh sai thang/phương thức              |
|       8 | EC-14: Điểm sát cutoff                          | Tránh hứa hẹn đỗ sai                             |
|       9 | EC-16: Hai nguồn conflict về cutoff             | Thể hiện giá trị conflict-aware                  |
|      10 | EC-18: Chỉ có dữ liệu năm trước                 | Tránh dùng dữ liệu lịch sử như kết luận hiện tại |
|      11 | EC-19: Phù hợp điểm nhưng vượt học phí          | Kiểm tra ranking đa tiêu chí                     |
|      12 | EC-24: Không có exact match                     | Kiểm tra tính trung thực của agent               |

---

# Mẫu test case dạng Given / When / Then

Bạn có thể chuẩn hóa mỗi edge case theo format sau:

```markdown
### EC-12 — High score but unsupported subject combination

**Given**
- admission_year = 2026
- admission_method = national_exam_score
- total_score = 28.0
- subject_combination = D01
- target program accepts only A00 and A01
- reference_cutoff = 26.5

**When**
- The recommendation engine evaluates the target program.

**Then**
- eligibility.status = NOT_ELIGIBLE
- eligibility.reason identifies unsupported subject combination
- score_fit is not calculated or not used for recommendation
- the program is not labelled as safer/competitive
```

---

## Kết luận

Các edge case quan trọng nhất không nằm ở việc model có hiểu câu dài phức tạp hay không, mà nằm ở việc hệ thống có giữ đúng nguyên tắc nghiệp vụ hay không:

* **Không đánh giá điểm khi thiếu phương thức hoặc sai tổ hợp.**
* **Không coi sở thích suy luận là ngành người dùng đã xác nhận.**
* **Không làm mất hoặc ghi đè dữ liệu khi người dùng bổ sung/sửa thông tin.**
* **Không che giấu conflict giữa các nguồn.**
* **Không khẳng định trúng tuyển dựa trên điểm tham chiếu lịch sử.**
* **Không bịa ra lựa chọn phù hợp khi không có kết quả đáp ứng constraint.**

Bộ edge case này sẽ giúp bạn kiểm thử đồng thời `profile inference`, `state update`, `retrieval gating`, `conflict detection`, `ranking` và phần giải thích đầu ra của advisor.
