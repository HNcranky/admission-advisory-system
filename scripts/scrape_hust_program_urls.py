"""One-off: dump all HUST undergraduate program URLs from the listing page.

The page at /training-cate/nganh-dao-tao-dai-hoc renders one card per program.
The intended target is the anchor at xpath
    /html/body/div/main/div/div/div[n]/div/div[6]/div/div/div[2]/a
where div[n] iterates per program. The page hydrates client-side, so the exact
positional xpath does not resolve against the static HTML — but every card's
detail anchor is present in markup. We select them by href prefix, which yields
exactly one URL per program (the same anchors the xpath targets).

Run:
    .venv/bin/python -m scripts.scrape_hust_program_urls
Writes scripts/hust_program_urls.txt (one absolute URL per line).

NOT part of the test suite (fetches the network at runtime).
"""

from __future__ import annotations

from pathlib import Path

import requests
import urllib3
from lxml import html

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

LISTING_URL = "https://ts.hust.edu.vn/training-cate/nganh-dao-tao-dai-hoc"
BASE = "https://ts.hust.edu.vn/"
HREF_PREFIX = "/training-cate/nganh-dao-tao-dai-hoc/"
OUT = Path(__file__).with_name("hust_program_urls.txt")


def fetch_program_urls() -> list[str]:
    resp = requests.get(LISTING_URL, timeout=30, verify=False)
    resp.raise_for_status()

    tree = html.fromstring(resp.content)
    tree.make_links_absolute(BASE)

    seen: set[str] = set()
    urls: list[str] = []
    for anchor in tree.xpath(f'//a[contains(@href, "{HREF_PREFIX}")]'):
        href = anchor.get("href", "").split("?")[0].rstrip("/")
        if href and href not in seen:
            seen.add(href)
            urls.append(href)
    return sorted(urls)


def main() -> None:
    urls = fetch_program_urls()
    OUT.write_text("\n".join(urls) + "\n", encoding="utf-8")
    print(f"{len(urls)} program URLs -> {OUT}")
    for url in urls:
        print(url)


if __name__ == "__main__":
    main()
