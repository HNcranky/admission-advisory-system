import logging

from services import build_default_gateway
from services.chat.hybrid_models import AdvisoryBlock, KnowledgeBlock
from services.inference.models import InferenceRequest

logger = logging.getLogger(__name__)

SYNTHESIS_SYSTEM_PROMPT = """
Bạn là trợ lý tổng hợp câu trả lời tư vấn tuyển sinh đại học Việt Nam.
Bạn nhận hai khối thông tin đã được chuẩn bị sẵn:
- Khối A (Dữ liệu tuyển sinh): kết quả phân tích điểm chuẩn / khả năng đậu.
- Khối B (Thông tin trường): các dữ kiện thực tế (học phí, chương trình, học bổng...).

Quy tắc bắt buộc:
- CHỈ sắp xếp, đối chiếu và diễn đạt lại nội dung trong hai khối được cung cấp.
- TUYỆT ĐỐI không thêm bất kỳ số liệu, sự kiện hay nhận định nào không có trong hai khối.
- Nếu một khối thiếu dữ liệu, nói rõ phần đó chưa có dữ liệu, không suy diễn.
- Trình bày thành hai mục rõ ràng: "Theo dữ liệu tuyển sinh" và "Thông tin trường".
- Khi so sánh nhiều trường, ưu tiên lập bảng đối chiếu ngắn gọn.
- Không tự liệt kê nguồn; hệ thống sẽ tự gắn nguồn.
- Trả lời bằng tiếng Việt, định dạng markdown.

Chỉ trả về nội dung câu trả lời cuối cùng cho người dùng, không trả JSON.
""".strip()


class SynthesisAgent:
    def __init__(self, gateway=None):
        self._gateway = gateway or build_default_gateway()

    def synthesize(self, advisory: AdvisoryBlock, knowledge: list, question: str) -> str:
        try:
            body = self._llm_synthesize(advisory, knowledge, question)
        except Exception as exc:
            logger.warning("LLM synthesis failed, falling back to concatenation: %r", exc)
            body = self._concatenate(advisory, knowledge)
        sources = self._merge_sources(advisory, knowledge)
        if sources:
            body = f"{body}\n\nNguồn:\n" + "\n".join(f"- {url}" for url in sources)
        return body

    def _llm_synthesize(self, advisory, knowledge, question) -> str:
        if hasattr(self._gateway, "is_available") and not self._gateway.is_available():
            raise RuntimeError("gateway unavailable")
        result = self._gateway.run(
            InferenceRequest(
                agent_name="synthesis_agent",
                task_type="hybrid_synthesis",
                system_prompt=SYNTHESIS_SYSTEM_PROMPT,
                user_prompt=self._build_user_prompt(advisory, knowledge, question),
                output_mode="free_text",
                temperature=0.0,
            )
        )
        text = (result.content or "").strip()
        if not text:
            raise ValueError("empty synthesis content")
        return text

    @staticmethod
    def _build_user_prompt(advisory, knowledge, question) -> str:
        lines = [f"Câu hỏi của người dùng: {question}", ""]
        lines.append("Khối A — Dữ liệu tuyển sinh:")
        if advisory.has_data and advisory.answer:
            lines.append(advisory.answer)
        else:
            lines.append("(chưa có dữ liệu)")
        lines.append("")
        lines.append("Khối B — Thông tin trường:")
        any_kb = False
        for block in knowledge:
            if block.has_data and block.answer:
                any_kb = True
                label = " · ".join(x for x in [block.school, block.topic] if x)
                prefix = f"[{label}] " if label else ""
                lines.append(f"{prefix}{block.answer}")
        if not any_kb:
            lines.append("(chưa có dữ liệu)")
        return "\n".join(lines)

    @staticmethod
    def _merge_sources(advisory: AdvisoryBlock, knowledge: list) -> list:
        urls = []
        for url in advisory.sources:
            if url and url not in urls:
                urls.append(url)
        for block in knowledge:
            for url in block.sources:
                if url and url not in urls:
                    urls.append(url)
        return urls

    @staticmethod
    def _concatenate(advisory: AdvisoryBlock, knowledge: list) -> str:
        parts = []
        if advisory.has_data and advisory.answer:
            parts.append(f"**Theo dữ liệu tuyển sinh:**\n{advisory.answer}")
        else:
            parts.append("**Theo dữ liệu tuyển sinh:** Hệ thống chưa có dữ liệu tư vấn cho câu hỏi này.")

        kb_lines = []
        for block in knowledge:
            if block.has_data and block.answer:
                label = block.school or ""
                kb_lines.append(f"- {label}: {block.answer}" if label else f"- {block.answer}")
        if kb_lines:
            parts.append("**Thông tin trường:**\n" + "\n".join(kb_lines))
        else:
            parts.append("**Thông tin trường:** Hệ thống chưa có dữ liệu cho phần này.")

        return "\n\n".join(parts)
