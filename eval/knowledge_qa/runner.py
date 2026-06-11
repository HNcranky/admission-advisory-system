from eval.knowledge_qa.gateways import build_model_gateway
from eval.knowledge_qa.models import GoldenCase
from services.knowledge.models import KnowledgeQAResult
from services.knowledge.qa_service import KnowledgeQAService


def _service_for(model: str) -> KnowledgeQAService:
    # Retrieval is bypassed (generate_from_chunks), so the repository/embedder are
    # never used — pass sentinels to avoid constructing real DB/embedding clients.
    return KnowledgeQAService(
        chunk_repository=object(),
        embedder=object(),
        gateway=build_model_gateway(model),
    )


def run_case(case: GoldenCase, model: str) -> KnowledgeQAResult:
    service = _service_for(model)
    chunks = [c.to_scored_chunk() for c in case.chunks]
    return service.generate_from_chunks(case.question, chunks)
