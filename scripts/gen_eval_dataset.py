r"""Generate a corpus-grounded QnA evaluation dataset.

Samples real `knowledge_chunks` (stratified by school + topic), and for each chunk
makes ONE LLM call that writes a natural Vietnamese student question + a reference
answer grounded ONLY in that chunk. Grounding-by-construction makes the downstream
correctness/faithfulness judges fair (the answer is provably in-corpus), avoiding
the domain-mismatch trap of the HSA/TSA `QnA-admission` set.

Spec: docs/superpowers/specs/2026-06-20-qna-eval-dataset-design.md

Outputs:
  - eval/knowledge_qa/qna_corpus_eval.json   (git-tracked dataset)
  - Langfuse dataset `qna-corpus-eval-v1`     (only with --push)

Run:
    # generate JSON only (review it, then push)
    .\.venv\Scripts\python.exe -m scripts.gen_eval_dataset
    # generate + upload to Langfuse
    .\.venv\Scripts\python.exe -m scripts.gen_eval_dataset --push

Needs (.env, auto-loaded): GEMINI key, DB up. --push also needs LANGFUSE_* keys.
Not part of the test suite — one-off generation driver over live DB + LLM.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import time
from collections import defaultdict
from pathlib import Path

try:  # standalone script: load .env the app normally loads for us
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from services.db import cursor
from services.knowledge.db import get_knowledge_db_connection
from services.inference.gateway import LLMGateway
from services.inference.models import InferenceError, InferenceRequest
from services.inference.registry import ModelRegistry
from services.inference.telemetry import InferenceTelemetry

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("gen_eval_dataset")

OUT_PATH = Path("eval/knowledge_qa/qna_corpus_eval.json")
DATASET_NAME = "qna-corpus-eval-v1"
MIN_CHUNK_LEN = 400          # short chunks rarely support a self-contained Q/A
GEN_MODEL = "gemini-2.5-flash"

# The free-tier Gemini key pool trips per-minute (RPM) cooldowns on a burst; a
# rate-limited call raises InferenceError and would silently drop the chunk. Retry
# with a wait absorbs the short-window exhaustion so every chunk gets a real
# generation (mirrors eval/knowledge_qa/run.py). Tune via env. A persistent
# failure after all attempts = likely a daily cap (RPD) → re-run after reset.
import os
RETRY_ATTEMPTS = int(os.getenv("GEN_RETRY_ATTEMPTS", "4"))
RETRY_WAIT_SECONDS = float(os.getenv("GEN_RETRY_WAIT_SECONDS", "65"))

SYSTEM_PROMPT = (
    "Bạn là chuyên gia tạo dữ liệu đánh giá cho trợ lý tư vấn tuyển sinh đại học. "
    "Từ một đoạn văn bản tuyển sinh, hãy viết MỘT câu hỏi mà thí sinh thực sự có thể "
    "hỏi, và câu hỏi đó phải TRẢ LỜI ĐƯỢC HOÀN TOÀN chỉ bằng đoạn văn bản đó. "
    "Sau đó viết câu trả lời NGẮN GỌN, CHÍNH XÁC, CHỈ dùng thông tin trong đoạn văn "
    "bản (không bịa, không thêm kiến thức ngoài). Cả câu hỏi và câu trả lời bằng "
    "tiếng Việt. Câu hỏi phải tự nhiên, KHÔNG sao chép nguyên văn câu trả lời. "
    'Trả về JSON: {"question": "...", "answer": "..."}'
)


def build_gen_gateway(model: str = GEN_MODEL) -> LLMGateway:
    """Flash gateway, no fallback, JSON out — mirrors eval/knowledge_qa/gateways.py."""
    registry = ModelRegistry(
        default_model=model,
        agent_overrides={
            "qna_dataset_gen": {
                "primary_model": model,
                "output_mode": "json",
                "max_retries": 1,
                "allow_fallback": False,
                "max_tokens": 600,
                "thinking_budget": 0,
            },
        },
    )
    return LLMGateway(registry=registry, telemetry=InferenceTelemetry())


# ---- sampling -------------------------------------------------------------

def _fetch_candidates() -> dict[tuple[str, str], list[dict]]:
    """All answerable chunks, bucketed by (school, topic), ordered by id."""
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    with cursor(get_knowledge_db_connection) as cur:
        cur.execute(
            """
            SELECT id, school, COALESCE(topic, '(null)'), chunk_text, source_url, program
            FROM knowledge_chunks
            WHERE length(chunk_text) > %s
            ORDER BY school, topic NULLS FIRST, id
            """,
            (MIN_CHUNK_LEN,),
        )
        for cid, school, topic, text, url, program in cur.fetchall():
            buckets[(school, topic)].append(
                {"id": cid, "school": school, "topic": topic,
                 "chunk_text": text, "source_url": url, "program": program}
            )
    return buckets


def _even_pick(rows: list[dict], k: int) -> list[dict]:
    """Pick k evenly-spaced rows (deterministic — no randomness)."""
    n = len(rows)
    if k >= n:
        return list(rows)
    if k == 1:
        return [rows[n // 2]]
    return [rows[round(i * (n - 1) / (k - 1))] for i in range(k)]


def _allocate(buckets: dict[tuple[str, str], list[dict]], per_school: int) -> list[dict]:
    """Spread `per_school` across each school's present topics, proportional to
    bucket size (min 1 per non-empty topic), then even-pick within each bucket."""
    by_school: dict[str, list[tuple[str, list[dict]]]] = defaultdict(list)
    for (school, topic), rows in buckets.items():
        by_school[school].append((topic, rows))

    selected: list[dict] = []
    for school, topic_rows in sorted(by_school.items()):
        total = sum(len(r) for _, r in topic_rows)
        remaining = per_school
        # largest-remainder-ish: proportional, min 1, capped at bucket size
        n_topics = len(topic_rows)
        for i, (topic, rows) in enumerate(sorted(topic_rows, key=lambda tr: -len(tr[1]))):
            if i == n_topics - 1:
                k = remaining                       # last topic soaks up the rest
            else:
                share = max(1, round(per_school * len(rows) / total))
                k = min(share, remaining - (n_topics - 1 - i))  # leave ≥1 for each later topic
            k = max(0, min(k, len(rows), remaining))
            if k:
                picked = _even_pick(rows, k)
                logger.info("sample %-7s %-16s %d/%d", school, topic, k, len(rows))
                selected.extend(picked)
                remaining -= k
    return selected


# ---- generation -----------------------------------------------------------

def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def _valid(question: str, answer: str) -> str | None:
    """Return a rejection reason, or None if the pair is good."""
    if not question or not answer:
        return "empty q/a"
    q, a = _norm(question), _norm(answer)
    if len(q) < 8:
        return "question too short"
    if q in a or a in q:                              # leakage: one contains the other
        return "leakage (q⊆a or a⊆q)"
    return None


def generate(chunks: list[dict], gateway: LLMGateway, delay: float) -> list[dict]:
    items: list[dict] = []
    seen_q: set[str] = set()
    drops: dict[str, int] = defaultdict(int)

    req_for = lambda ch: InferenceRequest(
        agent_name="qna_dataset_gen",
        task_type="qna_dataset_gen",
        system_prompt=SYSTEM_PROMPT,
        user_prompt=f"Đoạn văn bản:\n\n{ch['chunk_text']}",
        output_mode="json",
        temperature=0.0,
    )

    for ch in chunks:
        # Retry InferenceError with a wait — almost always a transient RPM cooldown.
        res = None
        for attempt in range(RETRY_ATTEMPTS):
            try:
                res = gateway.run(req_for(ch))
                break
            except InferenceError as exc:
                if attempt == RETRY_ATTEMPTS - 1:
                    logger.warning("chunk %s: inference error after %d attempts %r — skip",
                                   ch["id"], RETRY_ATTEMPTS, exc)
                    drops["inference_error"] += 1
                    break
                logger.info("chunk %s: rate-limited, wait %.0fs (attempt %d/%d)",
                            ch["id"], RETRY_WAIT_SECONDS, attempt + 1, RETRY_ATTEMPTS)
                time.sleep(RETRY_WAIT_SECONDS)
        if res is None:
            continue

        data = res.parsed_data or {}
        question = (data.get("question") or "").strip()
        answer = (data.get("answer") or "").strip()

        reason = (
            "structure_failure" if res.failure_type
            else _valid(question, answer)
        )
        if reason:
            logger.warning("chunk %s: drop (%s)", ch["id"], reason)
            drops[reason] += 1
            continue

        if _norm(question) in seen_q:
            drops["duplicate_question"] += 1
            continue
        seen_q.add(_norm(question))

        items.append({
            "input": question,
            "expected_output": answer,
            "metadata": {
                "school": ch["school"],
                "topic": None if ch["topic"] == "(null)" else ch["topic"],
                "source_chunk_id": ch["id"],
                "source_url": ch["source_url"],
                "program": ch["program"],
            },
        })
        if delay:
            time.sleep(delay)

    if drops:
        logger.info("drops: %s", dict(drops))
    return items


# ---- csv (for Langfuse UI dataset import) ---------------------------------

# Flat columns so the Langfuse UI CSV importer can map them: input -> Input,
# expected_output -> Expected output, the rest -> Metadata. utf-8-sig keeps
# Vietnamese readable in Excel too.
CSV_COLUMNS = ["input", "expected_output", "school", "topic",
               "source_chunk_id", "source_url", "program"]


def write_csv(items: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for it in items:
            md = it["metadata"]
            w.writerow({
                "input": it["input"],
                "expected_output": it["expected_output"],
                "school": md["school"],
                "topic": md["topic"] or "",
                "source_chunk_id": md["source_chunk_id"],
                "source_url": md["source_url"],
                "program": md["program"] or "",
            })
    logger.info("wrote %d rows -> %s", len(items), path)


# ---- push -----------------------------------------------------------------

def push_to_langfuse(items: list[dict]) -> None:
    from langfuse import get_client

    lf = get_client()
    if not lf.auth_check():
        raise SystemExit("Langfuse not authenticated. Set LANGFUSE_* env (in .env).")
    try:
        lf.create_dataset(name=DATASET_NAME,
                          description="Corpus-grounded QnA eval (auto-gen from chunks)")
    except Exception:
        pass  # already exists
    for it in items:
        lf.create_dataset_item(
            dataset_name=DATASET_NAME,
            id=f"chunk-{it['metadata']['source_chunk_id']}",  # idempotent re-push
            input=it["input"],
            expected_output=it["expected_output"],
            metadata=it["metadata"],
        )
    lf.flush()
    logger.info("pushed %d items to Langfuse dataset %s", len(items), DATASET_NAME)


# ---- main -----------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Generate corpus-grounded QnA eval dataset")
    ap.add_argument("--per-school", type=int, default=12, help="target items per school")
    ap.add_argument("--delay", type=float, default=2.0, help="inter-call delay (rate limit)")
    ap.add_argument("--push", action="store_true", help="upload to Langfuse after generating")
    ap.add_argument("--out", type=Path, default=OUT_PATH)
    ap.add_argument("--from-json", type=Path, default=None,
                    help="skip DB+LLM; just (re)emit CSV/push from an existing JSON")
    args = ap.parse_args()

    if args.from_json:
        # Convert-only: no DB, no LLM cost. Reuse an already-generated dataset.
        items = json.loads(args.from_json.read_text(encoding="utf-8"))
        logger.info("loaded %d items from %s", len(items), args.from_json)
    else:
        buckets = _fetch_candidates()
        logger.info("buckets: %s", {f"{s}/{t}": len(r) for (s, t), r in sorted(buckets.items())})

        chunks = _allocate(buckets, args.per_school)
        logger.info("selected %d chunks across %d schools", len(chunks),
                    len({c['school'] for c in chunks}))

        gateway = build_gen_gateway()
        items = generate(chunks, gateway, args.delay)

        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("wrote %d items -> %s", len(items), args.out)

    csv_path = (args.from_json or args.out).with_suffix(".csv")
    write_csv(items, csv_path)

    # per-(school,topic) produced summary
    by_group: dict[str, int] = defaultdict(int)
    for it in items:
        by_group[f"{it['metadata']['school']}/{it['metadata']['topic']}"] += 1
    print("\n=== produced (school/topic -> count) ===")
    for g in sorted(by_group):
        print(f"  {g:<28} {by_group[g]}")
    print(f"  TOTAL: {len(items)}")

    if args.push:
        push_to_langfuse(items)
    else:
        print("\nReview the JSON, then re-run with --push to upload to Langfuse.")


if __name__ == "__main__":
    main()
