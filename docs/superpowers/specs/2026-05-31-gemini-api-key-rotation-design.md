# Gemini API Key Rotation (Multi-Key Failover)

**Date:** 2026-05-31
**Status:** Implemented

---

## Problem

`GeminiProvider` giữ **một** `genai.Client` dựng từ một `GEMINI_API_KEY` duy nhất.
Khi key đó hết quota (HTTP 429 `RESOURCE_EXHAUSTED` — free tier giới hạn
20 request/ngày/model), provider raise `InferenceError`. Gateway hiện tại chỉ
fallback sang **model khác trên cùng key**, nên khi key đã cạn quota theo
project/day thì mọi lời gọi LLM đều thất bại và toàn hệ thống degrade về
rule-based (extraction, intent router, reasoning...).

Người dùng có nhiều Gemini API key và muốn hệ thống **tự động xoay vòng**: khi
một key bị rate-limit thì thử ngay key kế tiếp còn khỏe, đồng thời "cho key lỗi
nghỉ" một khoảng để các request sau bỏ qua nó.

**Nguyên nhân gốc rễ:** Không có tầng quản lý nhiều key + trạng thái sức khỏe
key. Ngoài ra `build_default_gateway()` được gọi **mới mỗi request**, nên trạng
thái cooldown không thể nằm trong instance provider/gateway — phải sống ở một
singleton cấp process.

---

## Mục đích

- Cấu hình được **nhiều** Gemini API key.
- Khi gặp lỗi **gắn với key** (429 quota, 401/403 auth, 5xx server) → thử lại
  **chính request đó** trên key khỏe kế tiếp; đánh dấu key lỗi "nghỉ" (cooldown).
- Khi **mọi** key đang nghỉ → raise `InferenceError` như cũ để call-site degrade
  graceful (không đổi hành vi degrade hiện tại).
- Lỗi **không gắn với key** (network thuần) → raise ngay, không xoay vòng (đổi
  key không cứu được).
- Tương thích ngược: chỉ có `GEMINI_API_KEY` đơn lẻ vẫn chạy như trước.

---

## Phạm vi

**Trong scope:**
- `GeminiKeyPool` — singleton cấp process giữ keys + client cache + cooldown + lock.
- Phân loại lỗi Gemini (`429/401/403/5xx` vs khác) + parse `retryDelay`.
- `GeminiProvider` đổi sang chạy vòng lặp xoay key qua pool.
- Config loader đọc `GEMINI_API_KEYS` (CSV) + `GEMINI_API_KEY` (tương thích).
- Cập nhật test provider hiện có sang mô hình inject pool/client_factory.

**Ngoài scope:**
- Không đổi `LLMGateway` và `ModelRegistry` (model-fallback giữ nguyên).
- Không thêm provider khác (chỉ Gemini).
- Không persist trạng thái cooldown ra DB/disk (chỉ in-memory theo process).
- Không xử lý riêng per-minute vs per-day quota (dùng chung cơ chế cooldown).

---

## Kiến trúc & Components

### 1. Phân loại lỗi — `services/inference/providers/gemini_errors.py`

Hàm thuần, không phụ thuộc SDK, dễ test:

```python
def extract_status_code(exc) -> int | None:
    """Lấy HTTP status từ google.genai ClientError (.code) hoặc dò 3 chữ số
    đầu trong chuỗi lỗi làm fallback."""

def is_rotatable_error(exc) -> bool:
    """True nếu status ∈ {429, 401, 403} hoặc 500 ≤ status < 600.
    Đây là các lỗi 'gắn với key' nên đáng để đổi key."""

def parse_retry_delay(exc) -> float | None:
    """Đọc 'retryDelay': '26s' (hoặc 'retry in 26.7s') từ payload 429.
    None nếu không tìm thấy → caller dùng cooldown mặc định."""
```

### 2. `GeminiKeyPool` — `services/inference/providers/key_pool.py`

```python
class KeyHandle:           # (key_id, client)  — key_id chỉ để định danh/cooldown
    key_id: str
    client: object

class GeminiKeyPool:
    def __init__(self, keys: list[str], *, client_factory,
                 cooldown_seconds: float = 60.0, now=time.monotonic):
        # khử trùng lặp + bỏ rỗng, giữ thứ tự; client tạo lazy & cache theo key
    def has_keys(self) -> bool
    def num_keys(self) -> int
    def acquire(self) -> KeyHandle | None     # round-robin, bỏ qua key đang cooldown; None nếu tất cả nghỉ
    def penalize(self, key_id: str, delay: float | None = None) -> None  # cooldown_until = now() + (delay or default)
```

- **Round-robin**: con trỏ `_cursor` để rải tải; mỗi `acquire` trả key khỏe kế
  tiếp và đẩy con trỏ qua nó.
- **Thread-safe**: mọi truy cập `_cooldown_until` / `_cursor` / `_clients` dưới
  `threading.Lock` (advisory chạy trong `ThreadPoolExecutor` nền).
- **Inject được**: `client_factory(api_key) -> client` và `now` cho test (fake
  client + fake clock), không chạm mạng.

### 3. Singleton accessor — trong `key_pool.py`

```python
def get_key_pool() -> GeminiKeyPool      # lazy-init từ env, double-checked lock
def reset_key_pool() -> None             # test hook
```

### 4. `GeminiProvider` — sửa `generate()` thành vòng lặp xoay key

```python
def __init__(self, api_key=None, *, pool=None, client_factory=None):
    # pool có sẵn → dùng; api_key truyền vào → pool 1-key cô lập;
    # không có gì → get_key_pool() (singleton từ env). is_available() = pool.has_keys()

def generate(self, request, policy):
    if not pool.has_keys(): raise InferenceError("no Gemini API key configured")
    last_exc = None
    for _ in range(pool.num_keys()):
        handle = pool.acquire()
        if handle is None:               # tất cả key đang cooldown
            break
        try:
            response = handle.client.models.generate_content(...)
        except Exception as exc:
            if is_rotatable_error(exc):
                pool.penalize(handle.key_id, parse_retry_delay(exc))
                last_exc = exc
                continue                 # thử key kế
            raise InferenceError(...) from exc   # lỗi không gắn key → dừng
        return _build_result(response, request, policy)   # thành công
    raise InferenceError(f"all Gemini keys exhausted/cooling down: {last_exc!r}")
```

Phần xử lý JSON/STRUCTURE_FAILURE (parse text, empty → STRUCTURE_FAILURE) tách
ra `_build_result()` giữ nguyên logic hiện tại.

### 5. Config — `ingestion/config/settings.py`

```python
GEMINI_API_KEYS = os.getenv("GEMINI_API_KEYS", "")          # CSV
GEMINI_KEY_COOLDOWN_SECONDS = float(os.getenv("GEMINI_KEY_COOLDOWN_SECONDS", 60))
# loader: split(",") của GEMINI_API_KEYS + [GEMINI_API_KEY] → strip → bỏ rỗng → dedupe giữ thứ tự
```

`.env.example` (nếu có) ghi chú cách dùng `GEMINI_API_KEYS=key1,key2,key3`.

---

## Luồng dữ liệu

```
gateway.run(request)
  → policy = registry.resolve(agent)
  → provider.generate(request, policy)        # provider = singleton-pool-backed
        → pool.acquire() → KeyHandle(key khỏe)
        → client.models.generate_content(...)
            ├─ OK            → _build_result → return
            ├─ 429/401/403/5xx → pool.penalize(key) → acquire key kế → lặp
            └─ network khác  → raise InferenceError (dừng)
        → hết key khỏe → raise InferenceError
  → (gateway) STRUCTURE_FAILURE → model-fallback (giữ nguyên)
  → InferenceError lọt ra → call-site degrade về rule-based (giữ nguyên)
```

Trạng thái cooldown nằm trong `GeminiKeyPool` singleton → **bền qua các request**
dù gateway/provider được dựng lại mỗi lần.

---

## Error handling

| Tình huống | Hành vi |
|---|---|
| 429 quota một key | penalize key (cooldown = retryDelay hoặc mặc định), thử key kế |
| 401/403 key sai/hết hạn | penalize key, thử key kế |
| 5xx Google server | penalize key, thử key kế |
| Network/timeout thuần | raise `InferenceError` ngay (không xoay vòng) |
| Mọi key đang cooldown | raise `InferenceError` → degrade graceful |
| Không cấu hình key nào | `is_available()=False` → call-site dùng rule-based ngay (như hiện tại) |

---

## Testing

**`gemini_errors`:** status từ ClientError có `.code`; fallback dò chuỗi; nhận
diện 429/401/403/503 là rotatable, 400/network là không; parse `retryDelay`
từ payload 429 mẫu (lấy đúng từ log thực: `"Please retry in 26.7s"` /
`'retryDelay': '26s'`).

**`GeminiKeyPool`:** acquire round-robin theo thứ tự; bỏ qua key đang cooldown;
penalize đặt cooldown đúng; key hồi phục sau khi vượt cooldown (fake clock);
mọi key cooldown → `acquire()` trả `None`; dedupe/bỏ rỗng khi khởi tạo; thread
an toàn (gọi đồng thời không vỡ trạng thái — test với nhiều thread).

**`GeminiProvider` (failover):**
- key1 raise 429, key2 OK → trả kết quả của key2, key1 bị penalize.
- mọi key raise 429 → `InferenceError`, tất cả bị penalize.
- lỗi không rotatable (vd `ValueError`/network) → raise ngay, **không** thử key kế.
- 1 key + 429 → `InferenceError` (tương thích hành vi cũ).
- JSON hợp lệ / rỗng / sai định dạng → parse / `STRUCTURE_FAILURE` (giữ nguyên).
- `GeminiProvider(api_key="x")` vẫn gọi `genai.Client(api_key="x")` (test cũ).

**Refactor test cũ:** các test set `provider._client` trực tiếp đổi sang inject
qua `client_factory`/`pool`. Phần assert hành vi (parse/structure/hard-error)
giữ nguyên ý nghĩa.

---

## Tương thích ngược & rủi ro

- Chỉ `GEMINI_API_KEY` → pool 1-key, hành vi y như hiện tại (chỉ thêm 1 vòng lặp
  cỡ 1).
- Cooldown in-memory theo process: restart app → reset (chấp nhận được; không cần
  bền vững vì quota là trạng thái phía Google).
- Free tier là per-day: sau cooldown mặc định 60s, key vẫn có thể 429 lại →
  tốn 1 call/khoảng để phát hiện rồi cooldown tiếp. Chấp nhận được; có thể nâng
  `GEMINI_KEY_COOLDOWN_SECONDS` nếu muốn ít thăm dò hơn.
- `retryDelay` parse sai/thiếu → fallback cooldown mặc định (an toàn).
