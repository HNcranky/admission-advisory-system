import unicodedata


def vietnamese_fold(text: str) -> str:
    """Bỏ dấu + lowercase + gộp khoảng trắng cho keyword matching tiếng Việt.

    Nguồn chân lý duy nhất (gom từ 4 bản lệch nhau, audit §2.2). "đ"/"Đ"
    (U+0111/U+0110) không có NFKD decomposition nên phải map sang d/D TRƯỚC,
    nếu không ascii-strip sẽ nuốt mất ("điểm" -> "iem").
    """
    text = text.replace("đ", "d").replace("Đ", "D")
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.lower().split())
