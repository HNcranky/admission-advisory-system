import logging
from dataclasses import dataclass

from ingestion.fetchers.http_fetcher import http_fetch
from ingestion.parsers.html_parser import parse_html
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


@dataclass
class KnowledgeIngestResult:
    source_url: str
    skipped: bool
    chunks_total: int = 0
    chunks_embedded: int = 0
    chunks_reused: int = 0


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
                school=source.school,
                topic=source.topic,
                program=source.program,
                year=source.year,
                document_type=source.document_type,
                chunk_text=c.chunk_text,
                content_hash=hashes[i],
                embedding=embeddings[i],
                source_url=source.source_url,
                span_start=c.span_start,
                span_end=c.span_end,
            ))

        self.doc_repo.mark_ingested(doc_id, content_hash)
        logger.info(
            "Ingested %s: %d chunks (%d embedded, %d reused)",
            source.source_url, len(chunks), len(to_embed_text), reused,
        )
        return KnowledgeIngestResult(
            source_url=source.source_url,
            skipped=False,
            chunks_total=len(chunks),
            chunks_embedded=len(to_embed_text),
            chunks_reused=reused,
        )

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
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    pipeline = KnowledgePipeline()
    results = pipeline.run_all() if args.all else pipeline.run_for_school(args.school)

    for r in results:
        if r.skipped:
            print(f"SKIP   {r.source_url} (unchanged)")
        else:
            print(f"OK     {r.source_url}  chunks={r.chunks_total} "
                  f"embedded={r.chunks_embedded} reused={r.chunks_reused}")
    print(f"Done: {len(results)} source(s) processed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
