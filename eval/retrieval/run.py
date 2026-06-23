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
    return [c for c in data if c.get("metadata", {}).get("source_chunk_id")]


def _gold_texts(chunk_ids):
    """Map gold chunk id -> chunk_text straight from the knowledge store."""
    from services.knowledge.repository import get_knowledge_db_connection

    conn = get_knowledge_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, chunk_text FROM knowledge_chunks WHERE id = ANY(%s)",
                (list(chunk_ids),),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return {row[0]: row[1] for row in rows}


def _rank_of_gold(retrieved, gold_text):
    """1-based rank of the gold chunk among retrieved chunks, or None if absent."""
    for i, chunk in enumerate(retrieved, start=1):
        if chunk.chunk_text == gold_text:
            return i
    return None


def main() -> None:
    from services.knowledge.qa_service import KnowledgeQAService

    corpus = _load_corpus()
    gold_ids = {c["metadata"]["source_chunk_id"] for c in corpus}
    gold_text_by_id = _gold_texts(gold_ids)

    service = KnowledgeQAService(top_k=K_MAX, cache_enabled=False)

    ranks = []
    missing_gold = 0
    skipped = []
    for case in corpus:
        meta = case["metadata"]
        gold_text = gold_text_by_id.get(meta["source_chunk_id"])
        if gold_text is None:
            # Gold chunk id no longer in the store (re-ingest changed ids).
            missing_gold += 1
            skipped.append(case["input"])
            continue
        retrieved = service.retrieve(
            case["input"], school=meta.get("school"), topic=meta.get("topic")
        )
        ranks.append(_rank_of_gold(retrieved, gold_text))
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
        f"Labelled set: `{CORPUS_PATH}` — {n} questions with a gold chunk, "
        "one relevant chunk each. Production retrieval path, read-only."
    )
    if missing_gold:
        lines.append(
            f"\n> {missing_gold} question(s) skipped: their gold `source_chunk_id` "
            "is no longer in the store (re-ingest changed chunk ids); re-curate to restore."
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
