"""One-off: dump VNU-UET undergraduate program-overview URLs + canonical names.

The listing page /chuong-trinh-dao-tao/ holds one anchor per program inside the
post body. The user-supplied locator is the xpath
    //*[@id="post-31423"]/div/p[n]/span/span/a
(one p[n] per program tab), i.e. the CSS selector
    #post-31423 > div > p > span > span > a

Each anchor points at a per-program page on uet-test.uet.edu.vn whose content
container is `.entry-content`. The canonical program name is derived from each
page's server-rendered <title> ("Chương trình đào tạo ngành <NAME> – Trường …")
because the listing anchor text occasionally drops a styled drop-cap letter.

Run:
    python -m scripts.scrape_uet_program_urls > scripts/vnu_uet_program_urls.txt
Writes one "<canonical name>\t<absolute url>" line per program, preceded by a
"# selector: .entry-content" comment.

NOT part of the test suite (fetches the network at runtime).
"""

from __future__ import annotations

import re
import sys
import warnings

warnings.filterwarnings("ignore")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from bs4 import BeautifulSoup

from ingestion.fetchers.http_fetcher import http_fetch
from ingestion.parsers.html_parser import parse_html

LISTING_URL = "https://uet.vnu.edu.vn/chuong-trinh-dao-tao/"
ANCHOR_SELECTOR = "#post-31423 > div > p > span > span > a"
CONTENT_SELECTOR = ".entry-content"
# "Chương trình đào tạo ngành <NAME> – Trường Đại học Công Nghệ …" → <NAME>
_TITLE_PREFIX = re.compile(r"^Chương trình đào tạo ngành\s+", re.I)
_TITLE_SUFFIX = re.compile(r"\s*[–-]\s*Trường Đại học.*$", re.I)


def _program_name(content_label: str | None, fallback: str) -> str:
    if content_label:
        name = _TITLE_SUFFIX.sub("", _TITLE_PREFIX.sub("", content_label)).strip()
        if name:
            return name
    return fallback.strip()


def collect() -> list[tuple[str, str]]:
    listing = http_fetch(LISTING_URL, timeout=30)
    soup = BeautifulSoup(listing.raw_content, "html.parser")
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for a in soup.select(ANCHOR_SELECTOR):
        href = (a.get("href") or "").split("?")[0].rstrip("/")
        if not href or href in seen:
            continue
        seen.add(href)
        anchor_text = a.get_text(" ", strip=True)
        try:
            page = http_fetch(href, timeout=30)
            parsed = parse_html(page.raw_content, href, selector=CONTENT_SELECTOR)
            name = _program_name(parsed.content_label, anchor_text)
            if not parsed.text.strip():
                sys.stderr.write(f"WARN empty content: {href}\n")
        except Exception as exc:  # one bad page must not abort discovery
            sys.stderr.write(f"WARN fetch/parse failed {href}: {exc!r}\n")
            name = anchor_text
        out.append((name, href))
    return out


def main() -> int:
    rows = collect()
    print(f"# selector: {CONTENT_SELECTOR}")
    print(f"# source-listing: {LISTING_URL}")
    for name, url in rows:
        print(f"{name}\t{url}")
    sys.stderr.write(f"{len(rows)} program URLs collected\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
