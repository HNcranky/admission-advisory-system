# Docker Postgres DB Migration — Design

**Date:** 2026-05-19
**Status:** Draft (awaiting user review)
**Owner:** advisory-agent team
**Related:** [`db/setup_db.py`](../../../db/setup_db.py), [`ingestion/config/settings.py`](../../../ingestion/config/settings.py), [`db/migrations/`](../../../db/migrations/)

---

## 1. Problem & Goal

Postgres hiện được chạy như Windows service local (`postgresql-x64-18`). Setup hiện tại có 3 vấn đề:

1. **Friction onboarding:** dev mới phải tự cài Postgres Windows trước khi clone repo, dễ sai version/port/password.
2. **State ngầm:** password mặc định `"1"` hard-coded trong `ingestion/config/settings.py:40`; ai đổi password khi cài service sẽ gãy.
3. **Trạng thái không kiểm soát:** service `postgresql-x64-18` hiện đang `Stopped` trên máy hiện tại; lỗi không hiển nhiên cho dev đến khi chạy migration.

**Mục tiêu:**

- Thay Postgres host bằng Postgres container chạy qua `docker compose`, image `postgres:16-alpine`.
- Một lệnh `docker compose up -d db` đủ để có DB sạch, healthy, ready để migration.
- Migrations và seed registry tiếp tục chạy qua `python -m db.setup_db` từ host (logic Python không đổi).
- App Python tiếp tục chạy trên host, connect `localhost:5432` — drop-in replacement.
- Thêm integration tests chạy với Postgres Docker; tự skip nếu DB không reachable để không phá CI hiện tại.

## 2. Scope

**In scope:**
- `docker-compose.yml` ở root repo, 1 service Postgres duy nhất.
- Persistence qua named volume Docker.
- `.env.example` template + `.env` (gitignored) cho dev config.
- Update default password trong `ingestion/config/settings.py` (1 dòng).
- Folder `tests/integration/` với pytest marker `integration` + fixture skip-on-no-connection.
- README/QUICKSTART section hướng dẫn Docker setup.

**Out of scope:**
- Dockerize app Python (FastAPI, ingestion CLI).
- Multi-environment configs (staging, prod).
- Replication, backup automation, monitoring.
- Web admin UI (pgAdmin, adminer).
- Data migration từ Postgres 18 local (fresh start; data sẽ được tái tạo qua pipeline crawl).
- Gỡ Postgres Windows service (user tự làm sau khi xác nhận Docker ổn).

## 3. Decisions Log

| # | Quyết định | Đã chốt |
|---|---|---|
| 1 | Scope: Postgres-only trong Docker, app Python ở host | ✓ |
| 2 | Strategy data: fresh start, không migrate từ DB local | ✓ |
| 3 | Image: `postgres:16-alpine` (LTS, support đến 2028) | ✓ |
| 4 | Persistence: named volume Docker `advisory_pgdata` | ✓ |
| 5 | Init: giữ nguyên `python -m db.setup_db` từ host | ✓ |
| 6 | Port mapping: `5432:5432` (xung đột với service local đã Stopped — chấp nhận được) | ✓ |
| 7 | Credentials: `.env` (gitignored) + `.env.example` commit | ✓ |
| 8 | Tests: thêm integration tests; mặc định skip nếu DB không reachable | ✓ |
| 9 | Integration test infra: dev tự `docker compose up db`, pytest detect connection (không dùng testcontainers) | ✓ |
| 10 | Default password đổi từ `"1"` → `"postgres"` trong `settings.py` | ✓ |

## 4. Architecture

```
┌──────────────────────────┐         ┌────────────────────────────┐
│ Host (Windows/macOS/Linux)│         │ Docker                     │
│                          │         │ ┌────────────────────────┐ │
│ python -m ingestion.main │ ──TCP─▶ │ │ db (postgres:16-alpine)│ │
│ python -m db.setup_db    │ :5432  │ │  volume: advisory_pgdata│ │
│ pytest -m integration    │         │ │  healthcheck: pg_isready│ │
│                          │         │ └────────────────────────┘ │
└──────────────────────────┘         └────────────────────────────┘
```

- **App boundary không đổi:** `psycopg2.connect(host="localhost", port=5432, ...)` hoạt động y như cũ. Container và app communicate qua TCP port mapped, không qua Docker network.
- **State persistence:** named volume `advisory_pgdata` (không phụ thuộc working directory, sống sót nếu rename repo).
- **Health gating:** healthcheck `pg_isready` để dev tools / integration tests biết khi DB ready (~5s từ cold start).

## 5. File Inventory

### Files mới

| Path | Mục đích |
|---|---|
| `docker-compose.yml` | Khai báo service `db` |
| `.env.example` | Template biến môi trường |
| `tests/integration/__init__.py` | Marker folder |
| `tests/integration/conftest.py` | Fixtures: `db_available` (skip-on-fail), `clean_db` |
| `tests/integration/test_db_writer_e2e.py` | Smoke test pipeline → DB → query |
| `pyproject.toml` | Đăng ký marker `integration` (nếu chưa có file) |

### Files sửa

| Path | Thay đổi |
|---|---|
| `ingestion/config/settings.py:40` | Default password `"1"` → `"postgres"` |
| `README.md` | Thêm section "Setup DB qua Docker" |
| `.gitignore` | Verify `.env` được ignore (likely đã có) |

### Files KHÔNG đổi

- `db/setup_db.py` — vẫn chạy từ host.
- `db/migrations/001..010_*.sql` — không đổi; được apply như cũ qua `setup_db.py`.
- `ingestion/storage/db_connection.py`, `db_writer.py` — không đổi.
- App code (`agents/`, `services/`, `web/`) — không đổi.

## 6. `docker-compose.yml`

```yaml
services:
  db:
    image: postgres:16-alpine
    container_name: advisory-db
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${DB_NAME:-admission}
      POSTGRES_USER: ${DB_USER:-postgres}
      POSTGRES_PASSWORD: ${DB_PASSWORD:-postgres}
    ports:
      - "${DB_PORT:-5432}:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER:-postgres} -d ${DB_NAME:-admission}"]
      interval: 5s
      timeout: 3s
      retries: 10
      start_period: 5s

volumes:
  pgdata:
    name: advisory_pgdata
```

**Quyết định thiết kế ghi chú:**

- `restart: unless-stopped`: container tự lên khi reboot máy; dev có thể `docker compose down` để dừng hoàn toàn.
- Tất cả env có default qua `${VAR:-fallback}` syntax: compose chạy được ngay cả khi `.env` chưa có.
- `container_name` cố định để lệnh `docker exec advisory-db psql ...` không cần lookup.
- Healthcheck dùng `pg_isready` chứ không phải `SELECT 1` vì rẻ hơn và là pattern khuyến nghị của Postgres official image.

## 7. Environment Config

### `.env.example` (commit)

```
DB_HOST=localhost
DB_PORT=5432
DB_NAME=admission
DB_USER=postgres
DB_PASSWORD=postgres

GEMINI_API_KEY=
```

### `.env` (gitignored — dev tự copy từ `.env.example`)

- File `.env` hiện tại chỉ có `GEMINI_API_KEY` → giữ giá trị đó, append thêm DB vars khi cần override.
- Default behavior: không có `.env` cũng chạy được vì `docker-compose.yml` và `settings.py` đều có fallback.

### Thay đổi `ingestion/config/settings.py`

```python
# line 40
"password": os.getenv("DB_PASSWORD", "postgres"),  # was: "1"
```

Lý do: Postgres official image không chấp nhận `POSTGRES_PASSWORD=1` (yêu cầu password đủ mạnh ở một số version); đồng thời align với default trong `.env.example`. Đổi 1 ký tự không phá tương thích vì cả default lẫn override env đều chấp nhận.

## 8. Init / Migration Flow

### Setup lần đầu

```powershell
cp .env.example .env                       # (Windows: copy .env.example .env)
docker compose up -d db                    # container lên, healthcheck pass ~5s
python -m db.setup_db                      # tạo schema, run 10 migrations, seed registry
python -m ingestion.main --school vnu_uet  # smoke test
```

### Reset DB sạch

```powershell
docker compose down -v                     # -v xóa volume pgdata
docker compose up -d db
python -m db.setup_db
```

### Stop / restart (giữ data)

```powershell
docker compose stop db
docker compose start db
```

### Re-apply migrations (sau khi thêm migration mới)

```powershell
python -m db.setup_db                      # idempotent: migrations dùng IF NOT EXISTS / DO $$ pattern
```

**Verify trước khi merge:** scan `db/migrations/001..010_*.sql` đảm bảo tất cả idempotent. Migration 010 đã idempotent (dùng `DO $$ ... DROP CONSTRAINT IF EXISTS`). Cần verify 001-009 cùng pattern.

## 9. Integration Tests

### `pyproject.toml`

```toml
[tool.pytest.ini_options]
markers = [
    "integration: tests that require a live Postgres database",
]
```

(Nếu repo đã có `pytest.ini` hoặc `setup.cfg` cấu hình pytest, đăng ký marker ở đó thay vì tạo `pyproject.toml`.)

### `tests/integration/conftest.py`

```python
import pytest
import psycopg2
from ingestion.config.settings import DB_CONFIG


@pytest.fixture(scope="session")
def db_available():
    try:
        conn = psycopg2.connect(**DB_CONFIG, connect_timeout=2)
        conn.close()
    except psycopg2.OperationalError:
        pytest.skip(
            "Postgres not reachable; run `docker compose up -d db && python -m db.setup_db` first"
        )


@pytest.fixture
def clean_db(db_available):
    """Truncate canonical_admission_records before each test, keep registry seed."""
    conn = psycopg2.connect(**DB_CONFIG)
    with conn.cursor() as cur:
        cur.execute("TRUNCATE canonical_admission_records RESTART IDENTITY CASCADE")
    conn.commit()
    conn.close()
    yield
```

### `tests/integration/test_db_writer_e2e.py`

```python
import pytest

from ingestion.pipeline.ingestion_pipeline import IngestionPipeline
from ingestion.storage.db_connection import get_cursor
from ingestion.storage.db_writer import save_canonical_records

pytestmark = pytest.mark.integration


def test_vnu_uet_pipeline_persists_canonical_records(clean_db):
    records = IngestionPipeline().run_for_school("vnu_uet")
    assert len(records) == 20  # PDF only, after dự bị fix

    saved = save_canonical_records(records)
    assert saved == 20

    with get_cursor(commit=False) as cur:
        cur.execute(
            "SELECT COUNT(*) FROM canonical_admission_records "
            "WHERE school_id=%s AND admission_year=%s",
            ("vnu_uet", 2026),
        )
        assert cur.fetchone()[0] == 20


def test_per_source_uniqueness_constraint_exists(db_available):
    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT conname FROM pg_constraint
            WHERE conrelid = 'canonical_admission_records'::regclass
              AND contype = 'u'
        """)
        names = {row[0] for row in cur.fetchall()}
    assert "canonical_admission_records_per_source_key" in names
```

### Chạy tests

```powershell
# Cả unit + integration:
docker compose up -d db
python -m db.setup_db
pytest

# Chỉ unit (CI hoặc dev không có Docker):
pytest -m "not integration"

# Chỉ integration:
pytest -m integration
```

**Caveat:** smoke test fetch live PDF từ internet — offline sẽ fail với network error. Acceptable vì pipeline crawl bản chất cần network. Nếu sau này muốn deterministic, mock `_extract_pdf_text` qua conftest.

## 10. Operational Cheatsheet

| Tình huống | Lệnh |
|---|---|
| Start lần đầu | `docker compose up -d db && python -m db.setup_db` |
| Start hàng ngày | `docker compose start db` |
| Stop | `docker compose stop db` |
| Reset hoàn toàn | `docker compose down -v && docker compose up -d db && python -m db.setup_db` |
| Xem log Postgres | `docker compose logs -f db` |
| Mở psql trong container | `docker compose exec db psql -U postgres -d admission` |
| Dump schema | `docker compose exec -T db pg_dump -U postgres -s admission > schema.sql` |
| Backup data | `docker compose exec -T db pg_dump -U postgres admission > backup.sql` |

### Cleanup Postgres local (optional, sau khi Docker ổn)

```powershell
Stop-Service postgresql-x64-18
Set-Service postgresql-x64-18 -StartupType Disabled
# Hoặc gỡ qua "Programs and Features" nếu chắc chắn không dùng.
```

Không nằm trong PR migration; là step manual.

## 11. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Port 5432 xung đột nếu Postgres 18 local start lại | Doc rõ trong README; dev đổi `DB_PORT=5433` trong `.env` nếu cần. |
| Dev quên `docker compose up` trước khi chạy app | Integration tests tự skip; CLI fail rõ ràng với `connection refused` (đủ rõ, không cần guard). |
| Default password `"postgres"` lộ trên repo public | Dev default only; production phải dùng `.env` riêng. README warn. |
| Volume `advisory_pgdata` không tự xóa khi `docker compose down` | Đúng spec — chỉ xóa qua `-v`. Doc rõ. |
| Migration cũ (001-009) không idempotent → re-run `setup_db` fail | Verify trước merge: scan tất cả migrations đảm bảo dùng `IF NOT EXISTS` / `DO $$`. |
| Windows path / line-ending khi mount volume | Dùng named volume thay vì bind mount → tránh hoàn toàn. |
| Postgres 16 vs 18 incompatibility với SQL hiện tại | Migrations 001-010 dùng feature stable (CREATE TABLE, JSONB, UNIQUE, trigger). Không có feature ≥17. Compat 16. |

## 12. Acceptance Criteria

Spec coi như hoàn thành khi tất cả các điều kiện sau pass:

1. `docker compose up -d db` chạy thành công trên máy clean (Docker Desktop đã cài), không cần config thêm.
2. Healthcheck `pg_isready` trả về healthy trong < 10s sau khi container start.
3. `python -m db.setup_db` từ host apply hết 10 migrations và seed 2 VNU-UET sources, exit code 0.
4. `python -m ingestion.main --school vnu_uet` chạy hết pipeline và in 20 records (không cần đổi config).
5. `pytest -m integration` pass (smoke test pipeline → DB query).
6. `pytest -m "not integration"` pass mà KHÔNG cần Docker chạy (preserve current behavior — unit tests độc lập).
7. `docker compose down && docker compose start db` giữ nguyên data.
8. `docker compose down -v` xóa volume; chạy lại `setup_db` cho DB hoàn toàn sạch.
9. `.env.example` được commit; `.env` thực không commit.
10. README có section hướng dẫn Docker setup với link đến spec này.

## 13. Next Steps

Sau khi spec này được approve:

1. Tạo implementation plan qua `superpowers:writing-plans` skill (chia task: compose file, env config, settings.py edit, integration test infra, README, manual verification).
2. Thực thi plan qua `superpowers:executing-plans` skill.
3. Manual verify 10 acceptance criteria trước khi merge.
