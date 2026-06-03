Đúng vấn đề bạn đang thấy là **agent đang bị “task-oriented quá mức”**: nó được thiết kế để đi theo một luồng tư vấn tuyển sinh cố định, nên khi user hỏi câu bên lề như “học phí thế nào?”, “chương trình học gồm gì?”, “cơ hội việc làm ra sao?”, agent vẫn cố ép câu hỏi đó vào flow “tư vấn chọn ngành/chọn trường”.

Các hệ thống advisory agent hiện nay thường không xử lý bằng một flow duy nhất. Họ tách thành **2–4 lớp xử lý**.

## 1. Tách “luồng tư vấn chính” và “câu hỏi kiến thức bên lề”

Một advisory agent tốt thường có ít nhất 2 mode:

**Mode A — Advisory / Task flow**

Dùng khi user đang cần agent ra quyết định hoặc tư vấn theo quy trình, ví dụ:

> “Em muốn chọn ngành phù hợp với điểm thi của em”
> “So sánh giúp em ngành CNTT ở HUST và UET”
> “Với học lực này em nên đăng ký nguyện vọng nào?”

Mode này dùng dữ liệu có cấu trúc: ngành, tổ hợp xét tuyển, điểm chuẩn, quota, phương thức xét tuyển, điều kiện đầu vào, conflict giữa các nguồn.

**Mode B — Knowledge Q&A / RAG**

Dùng khi user hỏi thông tin bên lề, ví dụ:

> “Học phí trường này thế nào?”
> “Chương trình học ngành này gồm những môn gì?”
> “Trường này có ký túc xá không?”
> “Chuẩn đầu ra tiếng Anh là gì?”

Mode này nên dùng RAG trên tài liệu: website trường, đề án tuyển sinh, PDF chương trình đào tạo, trang học phí, FAQ, handbook.

Đây cũng là hướng các hệ thống hiện đại đang làm: dùng **routing** để quyết định câu hỏi nên đi vào flow nghiệp vụ hay đi vào knowledge/RAG. Ví dụ Rasa có cơ chế “coexistence router” để route message sang hệ thống NLU/flow hoặc CALM/LLM dựa trên nội dung câu hỏi; router có thể dựa vào intent hoặc LLM. ([Rasa][1]) Microsoft Copilot Studio cũng có hướng dùng knowledge sources và RAG để agent trả lời dựa trên dữ liệu tổ chức thay vì chỉ dựa vào model memory. ([Microsoft Learn][2])

## 2. Thêm một “Intent Router” ở đầu agent

Thay vì để advisory agent luôn xử lý mọi câu hỏi, nên có một bước đầu tiên:

```text
User message
   ↓
Intent Router
   ├── ADVISORY_FLOW: tư vấn chọn ngành / chọn trường / xét tuyển
   ├── KNOWLEDGE_QA: hỏi học phí / chương trình học / học bổng / ký túc xá
   ├── CLARIFICATION: thiếu thông tin, cần hỏi lại
   └── OUT_OF_SCOPE: ngoài phạm vi tuyển sinh
```

Ví dụ:

| User hỏi                                                   | Router nên phân loại                  |
| ---------------------------------------------------------- | ------------------------------------- |
| “Em được 25 điểm khối A00 nên chọn ngành nào?”             | `ADVISORY_FLOW`                       |
| “Học phí UET bao nhiêu?”                                   | `KNOWLEDGE_QA`                        |
| “Chương trình học ngành Khoa học máy tính gồm gì?”         | `KNOWLEDGE_QA`                        |
| “So sánh ngành CNTT HUST và UET theo học phí + điểm chuẩn” | `HYBRID`                              |
| “Thời tiết Hà Nội hôm nay thế nào?”                        | `OUT_OF_SCOPE` hoặc general assistant |

Điểm quan trọng: **router không trả lời câu hỏi**, nó chỉ quyết định “giao cho nhánh nào xử lý”.

Một số framework hiện nay cũng đi theo hướng hybrid: câu hỏi có intent rõ thì dùng response/flow định sẵn để nhanh và ổn định; câu hỏi phức tạp hoặc mở thì chuyển sang RAG/generative path. Một paper 2025 mô tả framework hybrid route theo intent confidence: predefined intents xử lý nhanh, còn câu hỏi phức tạp/ambiguous thì dùng RAG. ([arXiv][3])

## 3. Với hệ thống của bạn, nên thêm một nhánh `KnowledgeQAAgent`

Hiện tại bạn có vẻ đang có luồng:

```text
User → Admission Advisory Agent → tư vấn tuyển sinh theo flow
```

Nên đổi thành:

```text
User
 ↓
Admission Orchestrator
 ├── AdmissionAdvisorAgent
 │     → tư vấn chọn ngành, trường, phương thức xét tuyển
 │
 ├── KnowledgeQAAgent
 │     → trả lời học phí, chương trình học, học bổng, ký túc xá, chuẩn đầu ra
 │
 ├── CompareAgent
 │     → so sánh nhiều trường/ngành theo nhiều tiêu chí
 │
 └── FallbackAgent
       → hỏi lại hoặc báo không có dữ liệu
```

Trong đó `KnowledgeQAAgent` dùng RAG:

```text
question
  ↓
retrieve relevant chunks
  ↓
rerank
  ↓
generate answer with citations
  ↓
if not enough evidence → say "chưa tìm thấy dữ liệu"
```

Ví dụ user hỏi:

> “Học phí trường này như thế nào?”

Agent không nên trả lời bằng flow tư vấn tuyển sinh. Nó nên:

1. Xác định “trường này” đang refer tới trường nào trong context trước đó.
2. Tìm trong corpus các chunk liên quan đến `học phí`, `tuition`, `mức thu`, `đề án tuyển sinh`, `thông báo học phí`.
3. Trả lời có nguồn.
4. Nếu không có dữ liệu thì nói rõ: “Hiện tại hệ thống chưa ingest dữ liệu học phí của trường này.”

## 4. Nên có thêm loại intent `HYBRID`

Nhiều câu hỏi không thuần advisory cũng không thuần Q&A.

Ví dụ:

> “Với điểm của em thì nên chọn UET hay NEU, xét cả học phí và chương trình học?”

Câu này cần cả hai:

```text
Structured advisory data:
- điểm chuẩn
- phương thức xét tuyển
- quota
- điều kiện đầu vào

Unstructured knowledge:
- học phí
- chương trình học
- mô tả ngành
- học bổng
```

Với case này, orchestrator nên gọi cả:

```text
AdmissionAdvisorAgent + KnowledgeQAAgent
```

Sau đó tổng hợp thành một câu trả lời so sánh.

Đây là hướng rất hợp với thesis/project của bạn, vì hệ thống của bạn đã có phần **structured advisory** rồi. Phần còn thiếu là **unstructured knowledge access**. Trong nghiên cứu task-oriented dialog, vấn đề “câu hỏi trong task flow nhưng cần kiến thức từ tài liệu ngoài” thường được xử lý bằng các bước: phát hiện câu hỏi cần knowledge, chọn/retrieve tài liệu liên quan, rồi generate câu trả lời từ snippet. ([arXiv][4])

## 5. Đừng để advisory prompt “ôm hết mọi thứ”

Lỗi phổ biến là prompt của agent kiểu:

> “Bạn là trợ lý tư vấn tuyển sinh. Hãy luôn tư vấn ngành/trường phù hợp…”

Prompt như vậy khiến model cố kéo mọi câu hỏi về tư vấn tuyển sinh.

Nên tách prompt:

### Orchestrator prompt

Nhiệm vụ chính: phân loại câu hỏi, chọn agent/tool phù hợp.

Ví dụ output:

```json
{
  "route": "KNOWLEDGE_QA",
  "reason": "User asks about tuition fee, not admission recommendation",
  "entities": {
    "school": "VNU-UET",
    "topic": "tuition"
  }
}
```

### Advisor prompt

Chỉ xử lý tư vấn chọn ngành/trường.

### KnowledgeQA prompt

Chỉ trả lời dựa trên tài liệu retrieve được.

Quan trọng: `KnowledgeQAAgent` phải có rule:

```text
Nếu không tìm thấy bằng chứng trong tài liệu, không được bịa.
Hãy nói rõ dữ liệu chưa có hoặc cần bổ sung nguồn.
```

Microsoft cũng mô tả RAG trong Copilot Studio theo hướng dùng trusted/organization-specific knowledge để câu trả lời grounded vào nội dung doanh nghiệp, thay vì dựa vào memory của model. ([Microsoft Learn][5])

## 6. Cần thiết kế corpus khác nhau cho advisory và Q&A

Bạn không nên chỉ có bảng structured records kiểu:

```text
program
method
quota
score
source
```

Vì nó không đủ để trả lời:

> “Chương trình học gồm những môn gì?”

Cần thêm corpus dạng document chunks:

```text
raw_documents
document_chunks
embeddings
metadata
```

Metadata nên có:

```text
school
program
year
document_type
topic
source_url
span
```

Ví dụ `document_type`:

```text
admission_scheme
tuition_page
curriculum_pdf
student_handbook
scholarship_policy
faq
```

Ví dụ `topic`:

```text
tuition
curriculum
admission
scholarship
dormitory
career_outcome
english_requirement
```

Khi user hỏi học phí, retrieval nên filter trước:

```text
school = current_school
topic = tuition
```

rồi mới vector search. Nếu không filter, nó dễ retrieve nhầm sang điểm chuẩn hoặc phương thức xét tuyển.

## 7. Nên có policy “không phá flow hiện tại”

Một điểm rất quan trọng: khi user đang ở giữa flow tư vấn, câu hỏi bên lề không nên làm mất state.

Ví dụ:

```text
User: Em muốn tư vấn ngành CNTT
Agent: Em cho anh biết điểm thi...
User: À học phí UET bao nhiêu?
Agent: [trả lời học phí]
Agent: Quay lại phần tư vấn, em cho anh biết điểm thi nhé.
```

Tức là hệ thống cần giữ:

```text
active_flow = admission_advisory
temporary_route = knowledge_qa
return_to_flow = true
```

Đây là khác biệt giữa chatbot đơn giản và advisory agent tốt. Agent không chỉ trả lời câu hỏi, mà còn biết **tạm rẽ nhánh rồi quay lại luồng chính**.

## 8. Đề xuất kiến trúc cụ thể cho hệ thống của bạn

Bạn có thể thiết kế như sau:

```text
AdmissionOrchestrator
│
├── classifyIntent(message, conversationState)
│
├── if route = ADVISORY_FLOW
│      call AdmissionAdvisorAgent
│
├── if route = KNOWLEDGE_QA
│      call retrieveKnowledge(question, filters)
│      call KnowledgeQAAgent
│
├── if route = HYBRID
│      call AdmissionAdvisorAgent
│      call retrieveKnowledge(...)
│      synthesize final answer
│
└── if route = CLARIFICATION
       ask focused follow-up question
```

Intent schema nên có dạng:

```ts
type AdmissionIntent =
  | "ADVISORY_FLOW"
  | "KNOWLEDGE_QA"
  | "HYBRID"
  | "CLARIFICATION"
  | "OUT_OF_SCOPE"

type KnowledgeTopic =
  | "tuition"
  | "curriculum"
  | "scholarship"
  | "dormitory"
  | "career"
  | "admission_policy"
  | "program_overview"
```

Với câu hỏi:

> “Vậy học phí trường này như thế nào?”

Router nên trả:

```json
{
  "route": "KNOWLEDGE_QA",
  "topic": "tuition",
  "school": "resolved_from_context",
  "returnToPreviousFlow": true
}
```

## 9. Câu trả lời ngắn gọn cho câu hỏi của bạn

Các advisory agent hiện nay thường **không dùng một luồng cứng duy nhất**. Họ dùng mô hình **hybrid**:

```text
Task flow / structured advisory
+
Intent router
+
RAG knowledge Q&A
+
Fallback/clarification
+
Conversation state để quay lại flow chính
```

Vấn đề của hệ thống bạn hiện tại là nó mới có phần:

```text
Task flow / structured advisory
```

nhưng còn thiếu:

```text
Intent router + KnowledgeQA/RAG branch
```

Vì vậy khi user hỏi “học phí”, “chương trình học”, “ký túc xá”, agent vẫn cố nhét vào luồng tư vấn tuyển sinh. Cách đúng là: **route câu hỏi đó sang KnowledgeQAAgent, trả lời dựa trên tài liệu, rồi quay lại luồng tư vấn nếu trước đó đang có flow active.**

[1]: https://rasa.com/docs/reference/config/components/coexistence-routers/?utm_source=chatgpt.com "Coexistence Routers | Rasa Documentation"
[2]: https://learn.microsoft.com/en-us/microsoft-copilot-studio/knowledge-copilot-studio?utm_source=chatgpt.com "Knowledge sources summary - Microsoft Copilot Studio"
[3]: https://arxiv.org/html/2506.02097v1?utm_source=chatgpt.com "Hybrid AI for Responsive Multi-Turn Online Conversations ..."
[4]: https://arxiv.org/abs/2102.04643?utm_source=chatgpt.com "Efficient Retrieval Augmented Generation from Unstructured Knowledge for Task-Oriented Dialog"
[5]: https://learn.microsoft.com/en-us/microsoft-copilot-studio/guidance/retrieval-augmented-generation?utm_source=chatgpt.com "Enhance AI responses with Retrieval Augmented Generation"
