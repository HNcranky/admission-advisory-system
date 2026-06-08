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


def probe_html() -> None:
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


API_URL = ("https://diemthi.tuyensinh247.com/api/common/cutoff-score"
           "?school_id={school}&method_id={method}&year={year}")


def probe_api(school: str, method: str, year: str, save: str | None) -> None:
    url = API_URL.format(school=school, method=method, year=year)
    r = http_fetch(url)
    import json as _json
    payload = _json.loads(r.raw_content)
    rows = payload.get("data") or []
    print(f"status={r.http_status} success={payload.get('success')} rows={len(rows)}")
    for row in rows[:5]:
        print(f"  {row.get('code')!r} | {(row.get('name') or '')[:45]!r} | "
              f"{row.get('block')!r} | {row.get('mark')}")
    if save:
        Path(save).write_bytes(r.raw_content)
        print(f"Đã lưu {len(r.raw_content)} bytes vào {save}")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "api":
        # python -m scripts._probe_tsn247_cutoff api <school_id> <method_id> <year> [out.json]
        probe_api(sys.argv[2], sys.argv[3], sys.argv[4],
                  sys.argv[5] if len(sys.argv) > 5 else None)
        return
    probe_html()


if __name__ == "__main__":
    main()
