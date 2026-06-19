import os
from pathlib import Path

                                                                  
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
INGESTION_ROOT = PROJECT_ROOT / "ingestion"
DATA_DIR = INGESTION_ROOT / "data"
RAW_CONTENT_DIR = DATA_DIR / "raw"
DICTIONARIES_DIR = INGESTION_ROOT / "normalization" / "dictionaries"


def _load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue

        os.environ[key] = value.strip().strip("\"'")


_load_env_file(PROJECT_ROOT / ".env")

                        
RAW_CONTENT_DIR.mkdir(parents=True, exist_ok=True)

                                                                  
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 5432)),
    "database": os.getenv("DB_NAME", "admission"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "postgres"),
}

                                                                  
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# --- Multi-key rotation (services/inference) -----------------------------
# Comma-separated extra keys, e.g. GEMINI_API_KEYS=key1,key2,key3. Combined with
# GEMINI_API_KEY (deduped) by services.inference.providers.key_pool.load_gemini_keys().
# When a key hits 429/auth/5xx it is "cooled down" for this many seconds (or the
# 429 retryDelay if larger) before the rotator will try it again.
GEMINI_KEY_COOLDOWN_SECONDS = float(os.getenv("GEMINI_KEY_COOLDOWN_SECONDS", 60))

# Hard timeout (giây) cho mỗi lời gọi Gemini generate/embed. Không có timeout
# thì connection treo sẽ giữ worker vô hạn và rotation key không bao giờ kích hoạt.
GEMINI_REQUEST_TIMEOUT_SECONDS = float(os.getenv("GEMINI_REQUEST_TIMEOUT_SECONDS", 60))


GEMINI_EXTRACTION_MODEL = os.getenv(
    "GEMINI_EXTRACTION_MODEL", "gemini-2.5-flash"
)


GEMINI_OCR_MODEL = os.getenv(
    "GEMINI_OCR_MODEL", "gemini-2.5-flash-lite"
)

# --- Embeddings (knowledge corpus / RAG) ---------------------------------
# gemini-embedding-001 with Matryoshka truncation to 768 dims. Changing
# EMBEDDING_DIM later requires re-embedding the whole corpus because the
# knowledge_chunks.embedding column type is fixed to vector(EMBEDDING_DIM).
GEMINI_EMBEDDING_MODEL = os.getenv(
    "GEMINI_EMBEDDING_MODEL", "gemini-embedding-001"
)
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", 768))

# --- Knowledge QA retrieval (Phase 4) ------------------------------------
# Top-K chunks pulled from pgvector before generation, and the minimum
# cosine score (score = 1 - distance) the top chunk must clear. Below it the
# QA service returns "no data" WITHOUT calling the LLM (zero-hallucination gate).
KNOWLEDGE_QA_TOP_K = int(os.getenv("KNOWLEDGE_QA_TOP_K", 5))
KNOWLEDGE_QA_MIN_SCORE = float(os.getenv("KNOWLEDGE_QA_MIN_SCORE", 0.5))
# Query-side program resolution (services/knowledge): the minimum
# word_similarity between a program label and the user's question for the
# program scalar filter to apply. Below it, retrieval stays vector-only so a
# weak/absent match never zeroes results.
KNOWLEDGE_PROGRAM_MATCH_THRESHOLD = float(
    os.getenv("KNOWLEDGE_PROGRAM_MATCH_THRESHOLD", 0.3)
)
# Separate, smaller budget for the national-scope (Bộ GD&ĐT) pass appended to
# every school-scoped knowledge query, so national regs never crowd out the
# school's own chunks.
KNOWLEDGE_QA_NATIONAL_TOP_K = int(os.getenv("KNOWLEDGE_QA_NATIONAL_TOP_K", 3))

# --- Knowledge QA semantic cache -----------------------------------------
# Cache repeated/paraphrased knowledge answers to cut Gemini generation calls.
# A HIT requires cosine >= THRESHOLD AND all dependency-scope versions current
# (see services/knowledge/qa_cache.py + docs spec 2026-06-18). TTL is a
# backstop only — correctness rests on version stamping. Any cache fault
# degrades to normal generation.
KNOWLEDGE_QA_CACHE_ENABLED = os.getenv(
    "KNOWLEDGE_QA_CACHE_ENABLED", "true"
).strip().lower() in ("1", "true", "yes")
KNOWLEDGE_QA_CACHE_THRESHOLD = float(os.getenv("KNOWLEDGE_QA_CACHE_THRESHOLD", 0.95))
KNOWLEDGE_QA_CACHE_TTL_DAYS = int(os.getenv("KNOWLEDGE_QA_CACHE_TTL_DAYS", 30))

# --- Knowledge chunking (Phase 3) ----------------------------------------
# Structure-aware char window. ~1800 chars ≈ 512 tokens for Vietnamese.
# Spans are character offsets → deterministic → stable idempotency key.
CHUNK_SIZE = int(os.getenv("KNOWLEDGE_CHUNK_SIZE", 1800))
CHUNK_OVERLAP = int(os.getenv("KNOWLEDGE_CHUNK_OVERLAP", 256))
# "whole_page" chunk strategy: emit the full page as ONE chunk, up to this many
# chars. Longer pages fall back to size-based splitting so a single embed call
# never exceeds the model's input limit (~2048 tokens ≈ 8000 Vietnamese chars).
WHOLE_PAGE_MAX_CHARS = int(os.getenv("KNOWLEDGE_WHOLE_PAGE_MAX_CHARS", 8000))


EMBED_CACHE_SIZE = int(os.getenv("EMBED_CACHE_SIZE", 512))

ADVISORY_RUN_WORKERS = int(os.getenv("ADVISORY_RUN_WORKERS", 2))
ADVISORY_RUN_QUEUE_MAX = int(os.getenv("ADVISORY_RUN_QUEUE_MAX", 32))

WEB_THREADPOOL_SIZE = int(os.getenv("WEB_THREADPOOL_SIZE", 40))

DB_POOL_ENABLED = os.getenv("DB_POOL_ENABLED", "true").lower() == "true"
DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", 1))
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", 10))

ADVISORY_DURABLE_QUEUE = os.getenv("ADVISORY_DURABLE_QUEUE", "true").lower() == "true"
ADVISORY_QUEUE_POLL_SECONDS = float(os.getenv("ADVISORY_QUEUE_POLL_SECONDS", 1.0))

FETCH_TIMEOUT = int(os.getenv("FETCH_TIMEOUT", 30))
FETCH_MAX_RETRIES = int(os.getenv("FETCH_MAX_RETRIES", 3))
FETCH_RETRY_BACKOFF = float(os.getenv("FETCH_RETRY_BACKOFF", 1.5))
# Default OFF: several official .gov.vn admission sources ship broken certs.
# Set ADVISORY_FETCH_VERIFY_SSL=true to enforce verification.
FETCH_VERIFY_SSL = os.getenv("ADVISORY_FETCH_VERIFY_SSL", "false").strip().lower() in (
    "1",
    "true",
    "yes",
)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

                                                                  
ADMISSION_KEYWORDS = [
    "tuyển sinh",
    "đề án",
    "chỉ tiêu",
    "xét tuyển",
    "phương thức",
    "điểm chuẩn",
    "tổ hợp môn",
    "ngành đào tạo",
    "admission",
    "enrollment",
]

                                                                  
                        
ADMISSION_YEAR = int(os.getenv("ADMISSION_YEAR", 2026))

                                         
LLM_MAX_CHUNK_SIZE = int(os.getenv("LLM_MAX_CHUNK_SIZE", 30000))
