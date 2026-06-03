from types import SimpleNamespace

from services.chat.conversation_service import ConversationService
from services.chat.intent_router import IntentResult
from services.chat.models import ChatProfileState, FlowState
from services.inference.models import InferenceResult
from services.knowledge.models import ScoredChunk
from services.knowledge.qa_service import KnowledgeQAService


class _ChatRepo:
    def __init__(self, profile, flow):
        self.profile_state = profile
        self.flow_state = flow
        self.messages = []
        self.status = "collecting_profile"

    def append_message(self, *args, **kwargs):
        self.messages.append(args)

    def get_session_by_token(self, token):
        return SimpleNamespace(session_token=token, status=self.status)

    def get_profile_state(self, token):
        return self.profile_state

    def update_profile_state(self, token, profile, status):
        self.profile_state = profile
        self.status = status

    def get_flow_state(self, token):
        return self.flow_state

    def update_flow_state(self, token, flow):
        self.flow_state = flow


class _Router:
    def __init__(self, result):
        self._result = result

    def classify(self, message, profile_state):
        return self._result


class _Embedder:
    def embed(self, texts, task_type="RETRIEVAL_DOCUMENT"):
        return [[0.1, 0.2, 0.3] for _ in texts]


class _Gateway:
    def __init__(self, parsed):
        self._parsed = parsed

    def run(self, request):
        return InferenceResult(
            agent_name=request.agent_name,
            model="test-model",
            provider="test",
            content="{}",
            parsed_data=self._parsed,
        )


class _Corpus:
    """In-memory mock corpus mimicking KnowledgeChunkRepository.vector_search."""

    def __init__(self, chunks):
        self._chunks = chunks

    def vector_search(self, embedding, school=None, topic=None, limit=5):
        matched = [
            c
            for c in self._chunks
            if (school is None or c.school == school)
            and (topic is None or c.topic == topic)
        ]
        return matched[:limit]


def _service(corpus, parsed, intent, profile=None):
    qa = KnowledgeQAService(
        chunk_repository=corpus,
        embedder=_Embedder(),
        gateway=_Gateway(parsed),
        min_score=0.5,
    )
    repo = _ChatRepo(profile or ChatProfileState(), FlowState())
    return ConversationService(
        repository=repo,
        extract_profile=lambda text, known_state=None, active_slot=None: {},
        intent_router=_Router(intent),
        knowledge_qa=qa,
    )


def test_knowledge_qa_end_to_end_grounded_answer_with_citations():
    corpus = _Corpus([
        ScoredChunk(
            school="VNU-UET",
            topic="tuition",
            chunk_text="Học phí VNU-UET năm 2026 là 35 triệu đồng/năm.",
            source_url="https://uet.vnu.edu.vn/hoc-phi",
            score=0.93,
        ),
    ])
    service = _service(
        corpus,
        parsed={
            "answer": "Học phí VNU-UET năm 2026 là 35 triệu đồng/năm.",
            "used_source_ids": [1],
        },
        intent=IntentResult(route="KNOWLEDGE_QA", topic="tuition", school="VNU-UET"),
        profile=ChatProfileState(preferred_schools=["VNU-UET"]),
    )

    result = service.handle_user_message("tok", "Học phí VNU-UET bao nhiêu?")

    assert result.should_start_run is False
    assert "35 triệu" in result.assistant_message
    assert "https://uet.vnu.edu.vn/hoc-phi" in result.assistant_message  # Nguồn appended
    assert len(result.citations) == 1
    assert result.citations[0].source_url == "https://uet.vnu.edu.vn/hoc-phi"
    assert "Học phí" in result.citations[0].chunk_text


def test_knowledge_qa_end_to_end_below_threshold_no_fabrication():
    corpus = _Corpus([
        ScoredChunk(
            school="VNU-UET",
            topic="tuition",
            chunk_text="Một đoạn không liên quan.",
            source_url="https://uet.vnu.edu.vn/x",
            score=0.2,  # below min_score → gate trips, LLM never consulted
        ),
    ])
    service = _service(
        corpus,
        parsed={"answer": "SỐ LIỆU BỊA KHÔNG ĐƯỢC DÙNG"},
        intent=IntentResult(route="KNOWLEDGE_QA", topic="tuition", school="VNU-UET"),
    )

    result = service.handle_user_message("tok", "Học phí bao nhiêu?")

    assert "chưa có dữ liệu" in result.assistant_message
    assert result.citations == []
    assert "BỊA" not in result.assistant_message
