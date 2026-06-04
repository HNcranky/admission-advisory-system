import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

from ingestion.fetchers.http_fetcher import http_fetch
from ingestion.parsers.html_parser import parse_html
from ingestion.knowledge.local_metadata import (
    build_gateway_classifier,
    load_overrides,
    metadata_from_override,
)
from ingestion.knowledge.pdf_ocr import build_gateway_ocr, extract_pages_hybrid
from ingestion.knowledge.pdf_pages import extract_pages, pages_to_marked_text
from ingestion.knowledge.chunker import split_into_chunks
from ingestion.knowledge.embedder import GeminiEmbedder
from ingestion.knowledge.registry.knowledge_registry import KnowledgeRegistry
from services.knowledge.models import KnowledgeChunk, KnowledgeDocument
from services.knowledge.repository import (
    KnowledgeChunkRepository,
    KnowledgeDocumentRepository,
    chunk_content_hash,
)

logger = logging.getLogger(__name__)

# Folder layout under --local-dir. Folder name doubles as document_type (D7);
# both folders run the SAME hybrid extractor — folder is intent, not command (D3).
LOCAL_FOLDERS = ("pdf_text", "pdf_scanned")


def _folder_intent_warnings(folder: str, hybrid, filename: str) -> list[str]:
    """Quality gate D3: folder is intent; mismatch warns but never blocks."""
    total = hybrid.pages_text + hybrid.pages_ocr + hybrid.pages_failed
    if total == 0:
        return []
    ocr_needed = hybrid.pages_ocr + hybrid.pages_failed
    if folder == "pdf_text" and ocr_needed * 2 > total:
        return [
            f"{filename} có vẻ là scan (>50% trang phải OCR), "
            "nên chuyển sang pdf_scanned/"
        ]
    if folder == "pdf_scanned" and hybrid.pages_text == total:
        logger.info(
            "%s: toàn bộ trang có text layer — không tốn call OCR nào", filename,
        )
    return []


@dataclass
class KnowledgeIngestResult:
    source_url: str
    skipped: bool
    chunks_total: int = 0
    chunks_embedded: int = 0
    chunks_reused: int = 0
    # Local-PDF (hybrid OCR) stats — stay at defaults for URL sources.
    pages_text: int = 0
    pages_ocr: int = 0
    pages_ocr_failed: int = 0
    school: str = ""
    year: int | None = None
    warnings: list[str] = field(default_factory=list)


class KnowledgePipeline:
    def __init__(self, registry=None, embedder=None, doc_repo=None,
                 chunk_repo=None, fetch=None):
        self.registry = registry if registry is not None else KnowledgeRegistry()
        self.embedder = embedder if embedder is not None else GeminiEmbedder()
        self.doc_repo = doc_repo if doc_repo is not None else KnowledgeDocumentRepository()
        self.chunk_repo = chunk_repo if chunk_repo is not None else KnowledgeChunkRepository()
        self.fetch = fetch if fetch is not None else http_fetch

    def _extract_text(self, fetch_result, url: str) -> str:
        ctype = (fetch_result.content_type or "").lower()
        if "pdf" in ctype or url.lower().endswith(".pdf"):
            return pages_to_marked_text(extract_pages(fetch_result.raw_content))
        return parse_html(fetch_result.raw_content, url).text

    def _chunk_embed_upsert(self, doc_id, text, *, school, topic, program,
                            year, document_type, source_url):
        """Chunk -> reuse/embed -> replace chunks for one document.

        Returns (chunks_total, chunks_embedded, chunks_reused).
        """
        chunks = split_into_chunks(text)
        hashes = [chunk_content_hash(c.chunk_text) for c in chunks]
        # Corpus-wide reuse: identical chunk text in ANY document reuses its
        # embedding, so re-ingestion never re-embeds text already seen.
        reuse = self.chunk_repo.get_embeddings_for_hashes(hashes)

        embeddings: list = [None] * len(chunks)
        to_embed_idx: list[int] = []
        to_embed_text: list[str] = []
        reused = 0
        for i, c in enumerate(chunks):
            h = hashes[i]
            if h in reuse:
                embeddings[i] = reuse[h]
                reused += 1
            else:
                to_embed_idx.append(i)
                to_embed_text.append(c.chunk_text)

        if to_embed_text:
            vectors = self.embedder.embed(to_embed_text)
            for idx, vec in zip(to_embed_idx, vectors):
                embeddings[idx] = vec

        self.chunk_repo.delete_chunks_for_document(doc_id)
        for i, c in enumerate(chunks):
            self.chunk_repo.upsert_chunk(KnowledgeChunk(
                knowledge_document_id=doc_id,
                school=school,
                topic=topic,
                program=program,
                year=year,
                document_type=document_type,
                chunk_text=c.chunk_text,
                content_hash=hashes[i],
                embedding=embeddings[i],
                source_url=source_url,
                span_start=c.span_start,
                span_end=c.span_end,
            ))
        return len(chunks), len(to_embed_text), reused

    def run_for_source(self, source) -> KnowledgeIngestResult:
        fr = self.fetch(source.source_url)
        content_hash = fr.content_hash

        existing = self.doc_repo.get_document_by_url(source.source_url)
        if existing is not None and existing.content_hash == content_hash:
            logger.info("Unchanged, skipping %s", source.source_url)
            return KnowledgeIngestResult(source_url=source.source_url, skipped=True)

        text = self._extract_text(fr, source.source_url)
        doc_id = self.doc_repo.get_or_create_document(KnowledgeDocument(
            school=source.school,
            document_type=source.document_type,
            source_url=source.source_url,
            raw_text=text,
        ))

        total, embedded, reused = self._chunk_embed_upsert(
            doc_id, text,
            school=source.school, topic=source.topic, program=source.program,
            year=source.year, document_type=source.document_type,
            source_url=source.source_url,
        )

        self.doc_repo.mark_ingested(doc_id, content_hash)
        logger.info(
            "Ingested %s: %d chunks (%d embedded, %d reused)",
            source.source_url, total, embedded, reused,
        )
        return KnowledgeIngestResult(
            source_url=source.source_url,
            skipped=False,
            chunks_total=total,
            chunks_embedded=embedded,
            chunks_reused=reused,
        )

    def run_for_local_file(self, pdf_path: Path, root: Path, overrides: dict,
                           ocr, classify) -> KnowledgeIngestResult:
        content = pdf_path.read_bytes()
        content_hash = hashlib.sha256(content).hexdigest()
        source_url = pdf_path.resolve().as_uri()      # citation trỏ về file gốc
        folder = pdf_path.relative_to(root).parts[0]  # "pdf_text" | "pdf_scanned"
        override_entry = overrides.get(pdf_path.name)

        existing = self.doc_repo.get_document_by_url(source_url)
        if existing is not None and existing.content_hash == content_hash:
            if override_entry is None:
                logger.info("Unchanged, skipping %s", source_url)
                return KnowledgeIngestResult(source_url=source_url, skipped=True)
            # Override on an unchanged file: re-chunk from the stored raw_text —
            # no extract/OCR cost; chunk embeddings are reused by content_hash.
            meta = metadata_from_override(override_entry)
            text = existing.raw_text or ""
            warnings: list[str] = []
            pages_text = pages_ocr = pages_failed = 0
        else:
            hybrid = extract_pages_hybrid(content, ocr)
            text = pages_to_marked_text(hybrid.to_page_tuples())
            first_pages = "\n\n".join(
                p.text for p in hybrid.pages[:2] if p.text.strip()
            )
            meta = classify(first_pages, pdf_path.name, overrides)
            warnings = list(meta.warnings)
            warnings += _folder_intent_warnings(folder, hybrid, pdf_path.name)
            pages_text, pages_ocr, pages_failed = (
                hybrid.pages_text, hybrid.pages_ocr, hybrid.pages_failed,
            )

        doc_id = self.doc_repo.get_or_create_document(KnowledgeDocument(
            school=meta.school,
            document_type=folder,
            source_url=source_url,
            raw_text=text,
        ))
        total, embedded, reused = self._chunk_embed_upsert(
            doc_id, text,
            school=meta.school, topic=None, program=None, year=meta.year,
            document_type=folder, source_url=source_url,
        )
        self.doc_repo.mark_ingested(doc_id, content_hash)
        logger.info(
            "Ingested %s: %d chunks (%d embedded, %d reused), "
            "pages text/ocr/failed=%d/%d/%d",
            source_url, total, embedded, reused,
            pages_text, pages_ocr, pages_failed,
        )
        return KnowledgeIngestResult(
            source_url=source_url, skipped=False,
            chunks_total=total, chunks_embedded=embedded, chunks_reused=reused,
            pages_text=pages_text, pages_ocr=pages_ocr,
            pages_ocr_failed=pages_failed,
            school=meta.school, year=meta.year, warnings=warnings,
        )

    def run_for_url(self, url: str, *, school: str,
                    document_type: str = "crawled_pdf",
                    ocr=None, classify=None) -> KnowledgeIngestResult:
        """Ingest a PDF straight from its URL using the hybrid extractor
        (text-layer + OCR). `school` comes from the crawl config (authoritative);
        the classifier only fills `year`. Citation = the school URL."""
        if ocr is None:
            ocr = build_gateway_ocr()
        if classify is None:
            classify = build_gateway_classifier()

        fr = self.fetch(url)
        content = fr.raw_content
        content_hash = fr.content_hash or hashlib.sha256(content).hexdigest()

        existing = self.doc_repo.get_document_by_url(url)
        if existing is not None and existing.content_hash == content_hash:
            logger.info("Unchanged, skipping %s", url)
            return KnowledgeIngestResult(source_url=url, skipped=True)

        hybrid = extract_pages_hybrid(content, ocr)
        text = pages_to_marked_text(hybrid.to_page_tuples())
        first_pages = "\n\n".join(
            p.text for p in hybrid.pages[:2] if p.text.strip()
        )
        filename = url.rsplit("/", 1)[-1] or url
        # school is authoritative from config; take only the year, ignore the
        # classifier's school + its school=unknown warning (irrelevant here).
        year = classify(first_pages, filename, {}).year

        doc_id = self.doc_repo.get_or_create_document(KnowledgeDocument(
            school=school, document_type=document_type,
            source_url=url, raw_text=text,
        ))
        total, embedded, reused = self._chunk_embed_upsert(
            doc_id, text, school=school, topic=None, program=None, year=year,
            document_type=document_type, source_url=url,
        )
        self.doc_repo.mark_ingested(doc_id, content_hash)
        logger.info(
            "Ingested %s: %d chunks (%d embedded, %d reused), "
            "pages text/ocr/failed=%d/%d/%d",
            url, total, embedded, reused,
            hybrid.pages_text, hybrid.pages_ocr, hybrid.pages_failed,
        )
        return KnowledgeIngestResult(
            source_url=url, skipped=False,
            chunks_total=total, chunks_embedded=embedded, chunks_reused=reused,
            pages_text=hybrid.pages_text, pages_ocr=hybrid.pages_ocr,
            pages_ocr_failed=hybrid.pages_failed,
            school=school, year=year, warnings=[],
        )

    def run_for_local_dir(self, root, ocr=None, classify=None) -> list[KnowledgeIngestResult]:
        """Auto-discovery (D4): scan <root>/pdf_text + <root>/pdf_scanned for
        *.pdf recursively — no per-file registration anywhere."""
        root = Path(root)
        if ocr is None:
            ocr = build_gateway_ocr()
        if classify is None:
            classify = build_gateway_classifier()
        overrides = load_overrides(root)

        results: list[KnowledgeIngestResult] = []
        for folder in LOCAL_FOLDERS:
            folder_path = root / folder
            if not folder_path.is_dir():
                logger.warning("Local folder missing, skipping: %s", folder_path)
                continue
            for pdf_path in sorted(folder_path.rglob("*.pdf")):
                try:
                    results.append(
                        self.run_for_local_file(pdf_path, root, overrides, ocr, classify)
                    )
                except Exception as exc:  # one bad file must not abort the run
                    logger.error("Local file failed %s: %r", pdf_path, exc)
        return results

    def run_for_school(self, school: str) -> list[KnowledgeIngestResult]:
        results: list[KnowledgeIngestResult] = []
        for source in self.registry.get_sources_by_school(school):
            try:
                results.append(self.run_for_source(source))
            except Exception as exc:  # one bad source must not abort the school
                logger.error("Source failed %s: %r", source.source_url, exc)
        return results

    def run_all(self) -> list[KnowledgeIngestResult]:
        results: list[KnowledgeIngestResult] = []
        for school in self.registry.schools():
            results.extend(self.run_for_school(school))
        return results


def _main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Ingest knowledge corpus")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--school", help="ingest one school, e.g. HUST")
    group.add_argument("--all", action="store_true", help="ingest all schools")
    group.add_argument(
        "--local-dir",
        help="ingest local PDFs from <dir>/pdf_text and <dir>/pdf_scanned",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    pipeline = KnowledgePipeline()
    if args.local_dir:
        results = pipeline.run_for_local_dir(Path(args.local_dir))
    elif args.all:
        results = pipeline.run_all()
    else:
        results = pipeline.run_for_school(args.school)

    for r in results:
        if r.skipped:
            print(f"SKIP   {r.source_url} (unchanged)")
        elif r.source_url.startswith("file://"):
            print(f"OK     {r.source_url} school={r.school} year={r.year} "
                  f"pages(text/ocr/fail)={r.pages_text}/{r.pages_ocr}/{r.pages_ocr_failed} "
                  f"chunks={r.chunks_total}")
        else:
            print(f"OK     {r.source_url}  chunks={r.chunks_total} "
                  f"embedded={r.chunks_embedded} reused={r.chunks_reused}")
        for w in r.warnings:
            print(f"WARN   {w}")
    print(f"Done: {len(results)} source(s) processed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
