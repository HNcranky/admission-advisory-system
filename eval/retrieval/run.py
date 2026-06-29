"""Retrieval-quality eval: Recall@k and MRR for the knowledge retriever.

    python -m eval.retrieval.run

The labelled set is `eval/knowledge_qa/qna_corpus_eval.json` — each question
carries the `source_chunk_id` of the chunk its gold answer was written from, i.e.
the single relevant chunk. For every question this harness runs the *production*
retrieval path (`KnowledgeQAService.retrieve`: embed → resolve program → pgvector
search → national augment) and checks at which rank the gold chunk appears. With
one relevant chunk per query, Recall@k is the hit-rate that the gold chunk is in
the top k, and MRR is the mean reciprocal of its rank.

Requirements: the dev database must be up and populated, and a Gemini key must be
present (one embedding call per question). The run is read-only.
"""

import json
import os
import time
from pathlib import Path

CORPUS_PATH = Path("eval/knowledge_qa/qna_corpus_eval.json")
REPORT_PATH = Path("docs/superpowers/evals/retrieval-recall.md")
K_VALUES = [1, 3, 5, 10]
K_MAX = max(K_VALUES)

# One embedding call per question; pace it so a free-tier key pool is not tripped.
CALL_DELAY_SECONDS = float(os.getenv("EVAL_CALL_DELAY_SECONDS", "1.0"))


def _load_corpus():
    data = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    return [c for c in data if c.get("metadata", {}).get("source_url")]


def _corpus_source_urls():
    """Source URLs currently present in the knowledge store. Gold is matched at
    DOCUMENT granularity (source URL), not chunk id: re-ingestion reassigns chunk
    ids, so the corpus's original `source_chunk_id` no longer identifies the same
    text, but the source URL of the document an answer was written from is stable.
    Recall@k then asks the standard document-retrieval question: did the top k
    chunks include one from the correct source document?"""
    from services.knowledge.db import get_knowledge_db_connection

    conn = get_knowledge_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT source_url FROM knowledge_chunks")
            return {r[0] for r in cur.fetchall()}
    finally:
        conn.close()


def _rank_of_gold(retrieved, gold_url):
    """1-based rank of the first retrieved chunk from the gold source document,
    or None if no retrieved chunk came from it."""
    for i, chunk in enumerate(retrieved, start=1):
        if (chunk.source_url or "") == gold_url:
            return i
    return None


def main() -> None:
    from services.knowledge.qa_service import KnowledgeQAService

    corpus = _load_corpus()
    present_urls = _corpus_source_urls()

    service = KnowledgeQAService(top_k=K_MAX, cache_enabled=False)

    ranks = []
    missing_gold = 0
    for case in corpus:
        meta = case["metadata"]
        gold_url = meta.get("source_url")
        if gold_url not in present_urls:
            # Gold document not in the current corpus (e.g. a local file ingested
            # on another machine, or a source dropped on re-ingest).
            missing_gold += 1
            continue
        retrieved = service.retrieve(
            case["input"], school=meta.get("school"), topic=meta.get("topic")
        )
        ranks.append(_rank_of_gold(retrieved, gold_url))
        if CALL_DELAY_SECONDS:
            time.sleep(CALL_DELAY_SECONDS)

    n = len(ranks)
    recall = {
        k: sum(1 for r in ranks if r is not None and r <= k) / n if n else 0.0
        for k in K_VALUES
    }
    mrr = sum((1.0 / r) for r in ranks if r is not None) / n if n else 0.0

    lines = ["# Retrieval-quality eval (Recall@k, MRR)", ""]
    lines.append(
        f"Labelled set: `{CORPUS_PATH}` — {n} questions scored. Gold is the source "
        "document (URL) the answer was written from; Recall@k = top-k chunks include "
        "one from that document. Production retrieval path, read-only."
    )
    if missing_gold:
        lines.append(
            f"\n> {missing_gold} question(s) skipped: their gold source document is "
            "not in the current corpus (local file from another machine, or dropped on re-ingest)."
        )
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    for k in K_VALUES:
        lines.append(f"| Recall@{k} | {recall[k]:.3f} |")
    lines.append(f"| MRR | {mrr:.3f} |")

    md = "\n".join(lines) + "\n"
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(md, encoding="utf-8")
    print(md)
    print(f"Report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
