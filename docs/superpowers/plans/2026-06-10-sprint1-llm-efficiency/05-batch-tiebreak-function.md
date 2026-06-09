# Slice 05: Hàm batch tiebreak

> Part of **Sprint 1 — LLM efficiency**. Spec: `docs/superpowers/specs/2026-06-10-sprint1-llm-efficiency-design.md`
> REQUIRED SUB-SKILL: superpowers:subagent-driven-development / superpowers:executing-plans. Slice này = một commit. Phụ thuộc: không.

**Goal:** Thêm `batch_interpret_conflict_tiebreak(pairs, gateway) -> dict[conflict_key, decision]` — một LLM call cho cả batch, degrade `{}` khi gateway unavailable / `InferenceError` / rỗng, bỏ qua entry thiếu `conflict_key`.

**Files:**
- Modify: `services/conflict/resolution_inference_service.py` (giữ nguyên `interpret_conflict_tiebreak`, `_serialize_option`)
- Test: `tests/services/conflict/test_resolution_inference_service.py`

---

- [ ] **Step 1: Write the failing test**

Thêm vào cuối `tests/services/conflict/test_resolution_inference_service.py` (helper `_record`, `_report`, `_Gateway` đã có sẵn):

```python
from services.conflict.resolution_inference_service import batch_interpret_conflict_tiebreak


def _record2():
    return ConflictRecord(
        conflict_key="hust:2026:ee:thpt", field_name="quota", school_id="hust",
        school_name="HUST", admission_year=2026, program_name="Ky thuat Dien",
    )


def test_batch_returns_decisions_keyed_by_conflict_key():
    gateway = _Gateway(parsed={"decisions": [
        {"conflict_key": "hust:2026:cs:thpt", "confidence": "high",
         "chosen_source_url": "https://a.test", "rationale": "r1"},
        {"conflict_key": "hust:2026:ee:thpt", "confidence": "low",
         "chosen_source_url": "https://b.test", "rationale": "r2"},
    ]})
    out = batch_interpret_conflict_tiebreak(
        [(_record(), _report()), (_record2(), _report())], gateway
    )
    assert out["hust:2026:cs:thpt"]["confidence"] == "high"
    assert out["hust:2026:ee:thpt"]["chosen_source_url"] == "https://b.test"


def test_batch_empty_pairs_makes_no_call():
    class _Boom:
        def is_available(self):
            return True

        def run(self, request):
            raise AssertionError("must not call gateway for empty batch")

    assert batch_interpret_conflict_tiebreak([], _Boom()) == {}


def test_batch_degrades_on_inference_error():
    gateway = _Gateway(exc=InferenceError("boom"))
    out = batch_interpret_conflict_tiebreak([(_record(), _report())], gateway)
    assert out == {}


def test_batch_degrades_when_gateway_unavailable():
    class _Unavailable:
        def is_available(self):
            return False

        def run(self, request):
            raise AssertionError("should not be called")

    out = batch_interpret_conflict_tiebreak([(_record(), _report())], _Unavailable())
    assert out == {}


def test_batch_skips_entries_missing_conflict_key():
    gateway = _Gateway(parsed={"decisions": [
        {"confidence": "high", "chosen_source_url": "https://a.test"},   # no conflict_key
        {"conflict_key": "hust:2026:cs:thpt", "confidence": "high",
         "chosen_source_url": "https://a.test", "rationale": "r"},
    ]})
    out = batch_interpret_conflict_tiebreak([(_record(), _report())], gateway)
    assert list(out.keys()) == ["hust:2026:cs:thpt"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/conflict/test_resolution_inference_service.py::test_batch_returns_decisions_keyed_by_conflict_key -v`
Expected: FAIL — `ImportError: cannot import name 'batch_interpret_conflict_tiebreak'`.

- [ ] **Step 3: Write minimal implementation**

Thêm vào `services/conflict/resolution_inference_service.py`:

```python
BATCH_RESOLUTION_SYSTEM_PROMPT = """
You are resolving SEVERAL conflicts between admission-data sources, each for one
program field. For EACH conflict choose the single most trustworthy source.
Prefer higher trust_level, more recent fetched_at, and higher confidence_score.
Never invent a value.
Return JSON: {"decisions": [ ... ]} with one entry per conflict, each entry:
- conflict_key: echo back exactly the conflict_key given for that conflict
- confidence: "high" or "low"
- chosen_source_url: the source_url of the option you trust most
- rationale: one short Vietnamese sentence explaining the choice
Use "high" only when one source is clearly more trustworthy than the others.
""".strip()


def batch_interpret_conflict_tiebreak(pairs, gateway) -> dict:
    """pairs: list[(ConflictRecord, ComparisonReport)] needing a tiebreak.

    One LLM call for the whole batch. Returns {conflict_key: decision_dict}.
    Degrades to {} (gateway unavailable / InferenceError / empty) so every caller
    treats a missing conflict_key as low-confidence (== unresolved).
    """
    if not pairs:
        return {}
    if hasattr(gateway, "is_available") and not gateway.is_available():
        return {}

    payload = {
        "conflicts": [
            {
                "conflict_key": record.conflict_key,
                "field_name": record.field_name,
                "school_name": record.school_name,
                "program_name": record.program_name,
                "admission_year": record.admission_year,
                "options": [_serialize_option(option) for option in report.ranked_options],
            }
            for record, report in pairs
        ]
    }
    try:
        result = gateway.run(
            InferenceRequest(
                agent_name="resolution_agent",
                task_type="conflict_tiebreak_batch",
                system_prompt=BATCH_RESOLUTION_SYSTEM_PROMPT,
                user_prompt=json.dumps(payload, ensure_ascii=False, default=str),
                output_mode="json",
                temperature=0.0,
            )
        )
    except InferenceError:
        return {}

    data = result.parsed_data or {}
    decisions = {}
    for entry in data.get("decisions", []) or []:
        if isinstance(entry, dict) and entry.get("conflict_key"):
            decisions[str(entry["conflict_key"])] = entry
    return decisions
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/conflict/test_resolution_inference_service.py -v`
Expected: PASS (test cũ + 5 test mới).

- [ ] **Step 5: Commit**

```bash
git add services/conflict/resolution_inference_service.py tests/services/conflict/test_resolution_inference_service.py
git commit -m "feat(conflict): add batch tiebreak resolving all indecisive conflicts in one call"
```
