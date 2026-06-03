from urllib.parse import urlparse

MOCK_LABELS = {
    "mock://uet/program-page": "Nguồn mock: UET program page",
    "mock://vnu/proposal-pdf": "Nguồn mock: VNU proposal PDF",
    "mock://uet/admission-news": "Nguồn mock: UET admission news",
}

HOST_LABELS = {
    "uet.vnu.edu.vn": "Trang tuyển sinh UET (ĐHQGHN)",
    "vnu.edu.vn": "Đề án tuyển sinh ĐHQGHN",
    "ts.hust.edu.vn": "Trang tuyển sinh HUST",
    "hust.edu.vn": "Trang tuyển sinh HUST",
}


def label_for_source(source_url: str) -> str:
    if not source_url:
        return "Nguồn không xác định"
    if source_url in MOCK_LABELS:
        return MOCK_LABELS[source_url]

    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "Nguồn không xác định"
    hostname = parsed.netloc.lower()
    return HOST_LABELS.get(hostname, f"Nguồn: {hostname}")
