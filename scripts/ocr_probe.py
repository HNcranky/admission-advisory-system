"""One-off probe: run the hybrid extractor on a real PDF and print the markdown.

Usage (cần GEMINI_API_KEY / GEMINI_API_KEYS export sẵn trong shell — repo không
dùng dotenv loader):

    .\\.venv\\Scripts\\python.exe scripts\\ocr_probe.py path\\to\\file.pdf --max-pages 3

NOT part of the test suite. OCR runs for EVERY image page of the file; --max-pages
only limits how many pages get printed.
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.knowledge.pdf_ocr import build_gateway_ocr, extract_pages_hybrid


def main() -> int:
    parser = argparse.ArgumentParser(description="Eyeball OCR quality on one PDF")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--max-pages", type=int, default=3,
                        help="print only the first N pages (default 3)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = extract_pages_hybrid(args.pdf.read_bytes(), build_gateway_ocr())

    print(f"pages: text={result.pages_text} ocr={result.pages_ocr} "
          f"failed={result.pages_failed}")
    for page in result.pages[: args.max_pages]:
        print(f"\n===== [Trang {page.page_no}] method={page.method} =====")
        print(page.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
