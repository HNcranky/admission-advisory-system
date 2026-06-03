from typing import List, Optional

_GREETING: List[str] = [
    "Chào bạn! Mình có thể giúp bạn tìm hiểu trường, ngành học hoặc thông tin tuyển sinh.",
    "Xin chào! Bạn đang muốn tìm hiểu trường, ngành hay phương thức xét tuyển nào?",
    "Chào bạn! Mình sẵn sàng giúp bạn tra cứu thông tin và cân nhắc lựa chọn phù hợp.",
]

_THANKS: List[str] = [
    "Rất vui được hỗ trợ bạn! Nếu cần thêm gì về tuyển sinh, cứ hỏi mình nhé.",
    "Không có gì đâu! Bạn còn muốn tìm hiểu thêm trường hay ngành nào không?",
]

_GOODBYE: List[str] = [
    "Chúc bạn ôn thi và xét tuyển thật tốt! Khi cần, mình luôn ở đây.",
    "Tạm biệt bạn nhé! Chúc bạn sớm chọn được trường, ngành ưng ý.",
]

_IDENTITY: List[str] = [
    "Mình là trợ lý tư vấn tuyển sinh đại học, giúp bạn tra cứu thông tin trường/ngành "
    "và cân nhắc lựa chọn dựa trên điểm số, nguyện vọng của bạn.",
]

_CAPABILITY: str = (
    "Mình là trợ lý tư vấn tuyển sinh. Mình có thể giúp bạn tìm hiểu trường và ngành "
    "học, tra cứu các thông tin như học phí hoặc chương trình đào tạo khi hệ thống có "
    "nguồn dữ liệu, đồng thời hỗ trợ bạn cân nhắc lựa chọn phù hợp dựa trên điểm số "
    "và nhu cầu của bạn. Bạn muốn bắt đầu với trường hay ngành nào?"
)

_EMOTIONAL_SUPPORT: str = (
    "Mình hiểu cảm giác lo lắng khi phải chọn trường và chờ kết quả. Nếu bạn chia "
    "sẻ điểm dự kiến, tổ hợp xét tuyển hoặc ngành quan tâm, mình có thể cùng bạn "
    "xem các lựa chọn thực tế hơn."
)


def _pick(variants: List[str], seed: int) -> str:
    return variants[seed % len(variants)]


def build_conversational_response(subtype: Optional[str], seed: int = 0) -> str:
    if subtype == "GREETING":
        return _pick(_GREETING, seed)
    if subtype == "THANKS":
        return _pick(_THANKS, seed)
    if subtype == "GOODBYE":
        return _pick(_GOODBYE, seed)
    if subtype == "IDENTITY":
        return _pick(_IDENTITY, seed)
    if subtype == "CAPABILITY":
        return _CAPABILITY
    if subtype == "EMOTIONAL_SUPPORT":
        return _EMOTIONAL_SUPPORT
    raise ValueError(f"unsupported conversational subtype: {subtype!r}")
