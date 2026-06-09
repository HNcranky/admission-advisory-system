# Slice 04: Parallel knowledge fan-out

> Part of **Sprint 1 — LLM efficiency**. Spec: `docs/superpowers/specs/2026-06-10-sprint1-llm-efficiency-design.md`
> REQUIRED SUB-SKILL: superpowers:subagent-driven-development / superpowers:executing-plans. Slice này = một commit. Phụ thuộc: không.

**Goal:** Chạy các cặp `(school, topic)` song song qua `ThreadPoolExecutor`, **giữ nguyên thứ tự block** và semantics "mỗi call tự nuốt lỗi → sibling vẫn sống". An toàn thread: `key_pool` có lock, repository mở connection riêng mỗi call.

**Files:**
- Modify: `services/chat/knowledge_fanout.py` (hàm `run_knowledge_fanout`)
- Test: `tests/services/chat/test_knowledge_fanout.py`

---

- [ ] **Step 1: Write the failing test**

Thêm vào cuối `tests/services/chat/test_knowledge_fanout.py`:

```python
import threading

from services.knowledge.models import KnowledgeQAResult


class _ConcurrentQA:
    """answer() chặn trên barrier `parties`; chỉ giải phóng khi đủ số call chạy
    đồng thời. Tuần tự → barrier timeout → max_concurrent < parties."""

    def __init__(self, parties):
        self._barrier = threading.Barrier(parties, timeout=2)
        self._lock = threading.Lock()
        self._active = 0
        self.max_concurrent = 0

    def answer(self, question, school, topic, conversation_context=""):
        with self._lock:
            self._active += 1
            self.max_concurrent = max(self.max_concurrent, self._active)
        try:
            self._barrier.wait()
        finally:
            with self._lock:
                self._active -= 1
        return KnowledgeQAResult(has_data=False, confidence=0.0)


def test_fanout_runs_pairs_concurrently():
    qa = _ConcurrentQA(parties=2)
    intent = IntentResult(route="HYBRID", schools=["A", "B"], topics=["t"])
    blocks = run_knowledge_fanout(qa, intent, "q")
    assert qa.max_concurrent == 2                      # hai call đồng thời
    assert [b.school for b in blocks] == ["A", "B"]    # thứ tự bảo toàn
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/chat/test_knowledge_fanout.py::test_fanout_runs_pairs_concurrently -v`
Expected: FAIL — code tuần tự: call đầu chờ barrier, timeout 2s → `BrokenBarrierError` (bị nuốt) → `max_concurrent == 1`.

- [ ] **Step 3: Write minimal implementation**

`services/chat/knowledge_fanout.py` — thêm import và hằng số đầu file:

```python
import logging
from concurrent.futures import ThreadPoolExecutor

from services.chat.hybrid_models import KnowledgeBlock

logger = logging.getLogger(__name__)

_FANOUT_MAX_WORKERS = 4
```

Thay nguyên hàm `run_knowledge_fanout` (giữ `_resolve_schools`, `_resolve_topics`, `format_knowledge_blocks` không đổi):

```python
def run_knowledge_fanout(knowledge_qa, intent, content, school_fallback=None, conversation_context="") -> list:
    """Call the single-school KnowledgeQA once per (school, topic) pair, in parallel.

    Each call swallows its own error → a no-data KnowledgeBlock; siblings survive.
    Block order matches the original (school, topic) iteration order.
    """
    tasks = [
        (school, topic)
        for school in _resolve_schools(intent, school_fallback)
        for topic in _resolve_topics(intent)
    ]

    def _answer_one(task):
        school, topic = task
        try:
            return knowledge_qa.answer(
                question=content, school=school, topic=topic,
                conversation_context=conversation_context,
            )
        except Exception as exc:
            logger.warning(
                "knowledge fan-out failed for school=%r topic=%r: %r", school, topic, exc
            )
            return None

    if len(tasks) <= 1:
        results = [_answer_one(task) for task in tasks]
    else:
        with ThreadPoolExecutor(max_workers=min(_FANOUT_MAX_WORKERS, len(tasks))) as executor:
            results = list(executor.map(_answer_one, tasks))

    blocks = []
    for (school, topic), result in zip(tasks, results):
        if result is not None and result.has_data and result.answer:
            sources = [c.source_url for c in result.citations if c.source_url]
            blocks.append(KnowledgeBlock(
                school=school, topic=topic, has_data=True,
                answer=result.answer, sources=sources,
            ))
        else:
            blocks.append(KnowledgeBlock(school=school, topic=topic, has_data=False))
    return blocks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/chat/test_knowledge_fanout.py -v`
Expected: PASS — test mới xanh; **tất cả test cũ vẫn xanh** (`executor.map` giữ thứ tự ⇒ order/nuốt-lỗi/fallback/context không đổi).

- [ ] **Step 5: Regression chat suite**

Run: `python -m pytest tests/services/chat -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add services/chat/knowledge_fanout.py tests/services/chat/test_knowledge_fanout.py
git commit -m "feat(chat): parallelize knowledge fan-out across (school, topic) pairs"
```
