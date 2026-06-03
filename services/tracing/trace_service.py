from services.chat.repository import ChatSessionRepository
from services.tracing.agent_tracer import STAGE_ORDER
from services.tracing.trace_repository import TraceRepository


class TraceService:
    def __init__(self, chat_repository=None, trace_repository=None):
        self.chat_repository = chat_repository or ChatSessionRepository()
        self.trace_repository = trace_repository or TraceRepository()

    def get_trace(self, session_token: str):
        session = self.chat_repository.get_session_by_token(session_token)
        if session is None:
            return None
        run_id = session.latest_run_id
        if run_id is None:
            return {"run_id": None, "run_status": None, "events": []}

        run_status = self.chat_repository.get_run_status(run_id)
        raw_events = self.trace_repository.list_events_for_run(run_id)
        by_stage = {e["stage"]: e for e in raw_events}

        events = []
        for sequence, stage in enumerate(STAGE_ORDER):
            if stage in by_stage:
                events.append(self._serialize_event(by_stage[stage]))
            else:
                events.append({
                    "stage": stage,
                    "sequence": sequence,
                    "status": "pending",
                    "started_at": None,
                    "completed_at": None,
                    "duration_ms": None,
                    "output_json": None,
                    "error_text": None,
                })

        return {"run_id": run_id, "run_status": run_status, "events": events}

    @staticmethod
    def _serialize_event(event: dict) -> dict:
        return {
            "stage": event["stage"],
            "sequence": event["sequence"],
            "status": event["status"],
            "started_at": event["started_at"].isoformat() if event["started_at"] else None,
            "completed_at": event["completed_at"].isoformat() if event["completed_at"] else None,
            "duration_ms": event["duration_ms"],
            "output_json": event["output_json"],
            "error_text": event["error_text"],
        }
