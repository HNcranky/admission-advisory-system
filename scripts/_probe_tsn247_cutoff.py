"""One-shot probe: trang điểm chuẩn BKA trên diemthi.tuyensinh247.com (Cutoff Plan 5).

Fetch trang thật, in số heading h3 khớp regex "điểm chuẩn theo phương thức … năm …",
số bảng, header + 3 row đầu mỗi bảng. Expected: 4 heading 2025, 4 bảng
`Tên ngành | Tổ hợp môn | Điểm chuẩn | Ghi chú`.

  python -m scripts._probe_tsn247_cutoff [--save tests/fixtures/tsn247_bka_cutoff_2025.html]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

from ingestion.fetchers.http_fetcher import http_fetch

URL = "https://diemthi.tuyensinh247.com/diem-chuan/dai-hoc-bach-khoa-ha-noi-BKA.html"

_HEADING_RE = re.compile(
    r"điểm chuẩn theo phương thức\s*(.+?)\s*năm\s*(20\d{2})", re.IGNORECASE
)


def main() -> None:
    r = http_fetch(URL)
    print(f"status={r.http_status} size={len(r.raw_content)}")

    soup = BeautifulSoup(r.raw_content, "html.parser")
    headings = []
    for h3 in soup.find_all("h3"):
        text = h3.get_text(" ", strip=True)
        m = _HEADING_RE.search(text)
        if m:
            headings.append((h3, m.group(1).strip(), int(m.group(2))))

    print(f"\nh3 khớp regex: {len(headings)} (tổng h3: {len(soup.find_all('h3'))}, "
          f"tổng table: {len(soup.find_all('table'))})")
    for h3, method, year in headings:
        print(f"\n=== {method!r} năm {year} ===")
        table = h3.find_next("table")
        if table is None:
            print("  KHÔNG có bảng kèm theo!")
            continue
        rows = table.find_all("tr")
        print(f"  rows: {len(rows)}")
        for row in rows[:4]:
            cells = [c.get_text(" ", strip=True)[:60] for c in row.find_all(["th", "td"])]
            print("  | ".join(cells))

    if "--save" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--save") + 1])
        # Cắt script/style/noscript/iframe cho nhẹ fixture — GIỮ NGUYÊN heading + bảng.
        for tag in soup.find_all(["script", "style", "noscript", "iframe"]):
            tag.decompose()
        data = soup.encode("utf-8")
        out.write_bytes(data)
        print(f"\nĐã lưu {len(data)} bytes (gốc {len(r.raw_content)}) vào {out}")


if __name__ == "__main__":
    main()
