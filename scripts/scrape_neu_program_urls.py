"""One-off: dump NEU undergraduate program-overview API URLs + canonical names.

NEU's program prose is NOT in the courses.neu.edu.vn SPA DOM (it lives in RSC
<script> data the HTML parser strips). The same host exposes an open Strapi REST
API whose per-program record carries the prose as *Html fields:
    https://courses.neu.edu.vn/api/curriculum-curricula?pagination[pageSize]=500
Each program is then seeded as the single-program query
    .../api/curriculum-curricula?filters[slug][$eq]=<slug>&populate=*
which the knowledge pipeline ingests via the JSON branch (ingestion/knowledge/
neu_api.py). See that module + the design spec.

The collection has many cohort rows per program (K66/K67/K68); INHERITED rows
leave the *Html fields empty (prose lives on the source cohort). So we group by
program name and keep ONE row that actually has prose (preferring the newest).

Run:
    python -m scripts.scrape_neu_program_urls > scripts/neu_program_urls.txt
Writes "<canonical name>\t<absolute api url>" lines, preceded by comments.

NOT part of the test suite (fetches the network at runtime).
"""

from __future__ import annotations

import json
import sys
import warnings

warnings.filterwarnings("ignore")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from ingestion.fetchers.http_fetcher import http_fetch
from ingestion.knowledge.neu_api import PROSE_FIELDS

API = "https://courses.neu.edu.vn/api/curriculum-curricula"
PROSE_KEYS = [k for k, _ in PROSE_FIELDS]


def _has_prose(attrs: dict) -> bool:
    return any((attrs.get(k) or "").strip() for k in PROSE_KEYS)


def _fetch_page(page: int) -> list[dict]:
    url = f"{API}?pagination[pageSize]=500&pagination[page]={page}"
    return json.loads(http_fetch(url, timeout=60).raw_content)["data"]


def collect() -> list[tuple[str, str]]:
    records: list[dict] = []
    for page in (1, 2):
        records.extend(_fetch_page(page))

    # name -> (year_sort_key, slug) for the best prose-bearing row.
    best: dict[str, tuple[str, str]] = {}
    for rec in records:
        attrs = rec.get("attributes", rec)
        name = (attrs.get("name") or "").strip()
        slug = (attrs.get("slug") or "").strip()
        if not name or not slug or not _has_prose(attrs):
            continue
        year = str(attrs.get("year") or "")  # e.g. "K66 - 2024"; newest sorts last
        if name not in best or year > best[name][0]:
            best[name] = (year, slug)

    rows = []
    for name in sorted(best):
        _, slug = best[name]
        url = f"{API}?filters[slug][$eq]={slug}&populate=*"
        rows.append((name, url))
    return rows


def main() -> int:
    rows = collect()
    print(f"# api-collection: {API}")
    print("# ingest: JSON branch in ingestion/knowledge/pipeline.py via neu_api.py")
    for name, url in rows:
        print(f"{name}\t{url}")
    sys.stderr.write(f"{len(rows)} NEU programs with prose collected\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
