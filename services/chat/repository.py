from contextlib import contextmanager

from fastapi.encoders import jsonable_encoder
from psycopg2.extras import Json

from services.chat.db import get_db_connection
from services.chat.models import ChatSessionRecord, ChatMessageRecord, ChatProfileState, FlowState


class ChatSessionRepository:
    def __init__(self, connection_factory=get_db_connection):
        self.connection_factory = connection_factory

    @contextmanager
    def _cursor(self, commit: bool = False):
        """Yield a cursor, guaranteeing commit/rollback and connection cleanup.

        Without this, any exception between connect and close() leaked the
        connection and left an uncommitted transaction open. These repository
        methods run inside background advisory threads, so leaks accumulate.
        """
        conn = self.connection_factory()
        try:
            cur = conn.cursor()
            try:
                yield cur
                if commit:
                    conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cur.close()
        finally:
            conn.close()

    def _jsonb(self, value):
        return Json(jsonable_encoder(value))

    def create_session(self, session_token: str) -> ChatSessionRecord:
        with self._cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO chat_sessions (session_token)
                VALUES (%s)
                RETURNING id, session_token, status, profile_state_json, latest_run_id
                """,
                (session_token,),
            )
            row = cur.fetchone()
        return ChatSessionRecord(
            id=row[0],
            session_token=row[1],
            status=row[2],
            profile_state_json=row[3] or {},
            latest_run_id=row[4],
        )

    def get_session_by_token(self, session_token: str):
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT id, session_token, status, profile_state_json, latest_run_id
                FROM chat_sessions
                WHERE session_token = %s
                """,
                (session_token,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return ChatSessionRecord(
            id=row[0],
            session_token=row[1],
            status=row[2],
            profile_state_json=row[3] or {},
            latest_run_id=row[4],
        )

    def append_message(self, session_token: str, role: str, content: str, kind: str = "chat"):
        with self._cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO chat_messages (session_id, role, kind, content)
                SELECT id, %s, %s, %s
                FROM chat_sessions
                WHERE session_token = %s
                RETURNING id
                """,
                (role, kind, content, session_token)
            )
            row = cur.fetchone()
        return ChatMessageRecord(
            id = row[0],
            session_token=session_token,
            role = role,
            kind = kind,
            content=content
        )

    def list_message(self, session_token: str):
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT m.id, s.session_token, m.role, m.kind, m.content
                FROM chat_messages m
                JOIN chat_sessions s ON s.id = m.session_id
                WHERE s.session_token = %s
                ORDER BY m.created_at ASC, m.id ASC
                """,
                (session_token,),
            )
            rows = cur.fetchall()
        return [
            ChatMessageRecord(
                id = row[0],
                session_token = row[1],
                role = row[2],
                kind = row[3],
                content = row[4],
            )
            for row in rows
        ]

    def get_profile_state(self, session_token: str):
        session = self.get_session_by_token(session_token)
        return ChatProfileState(**session.profile_state_json) if session else ChatProfileState()

    def get_flow_state(self, session_token: str) -> FlowState:
        with self._cursor() as cur:
            cur.execute(
                "SELECT flow_state_json FROM chat_sessions WHERE session_token = %s",
                (session_token,),
            )
            row = cur.fetchone()
        if not row:
            return FlowState()
        return FlowState(**(row[0] or {}))

    def update_flow_state(self, session_token: str, flow_state: FlowState) -> None:
        with self._cursor(commit=True) as cur:
            cur.execute(
                """
                UPDATE chat_sessions
                SET flow_state_json = %s, updated_at = NOW()
                WHERE session_token = %s
                """,
                (self._jsonb(flow_state), session_token),
            )

    def update_profile_state(self, session_token: str, profile_state, status: str):
        with self._cursor(commit=True) as cur:
            cur.execute(
                """
                UPDATE chat_sessions
                SET profile_state_json = %s, status = %s, updated_at = NOW()
                WHERE session_token = %s
                """,
                (self._jsonb(profile_state), status, session_token),
            )
        return profile_state

    def create_run(self, session_token: str, profile_state):
        with self._cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO chat_advisory_runs (session_id, profile_snapshot_json)
                SELECT id, %s
                FROM chat_sessions
                WHERE session_token = %s
                RETURNING id
                """,
                (self._jsonb(profile_state), session_token)
            )

            run_id = cur.fetchone()[0]
            cur.execute(
                """
                UPDATE chat_sessions
                SET latest_run_id = %s, status = 'running', updated_at = NOW()
                WHERE session_token = %s
                """,
                (run_id, session_token),
            )
        return run_id

    def mark_run_running(self, run_id: int):
        with self._cursor(commit=True) as cur:
            cur.execute(
                """
                UPDATE chat_advisory_runs
                SET status = 'running', started_at = NOW()
                WHERE id = %s
                """,
                (run_id,),
            )

    def complete_run(self, run_id: int, result_json, final_answer: str):
        with self._cursor(commit=True) as cur:
            cur.execute(
                """
                UPDATE chat_advisory_runs
                SET status = 'completed', result_json = %s, final_answer = %s, completed_at = NOW()
                WHERE id = %s
                """,
                (self._jsonb(result_json), final_answer, run_id)
            )

    def get_run_status(self, run_id: int):
        with self._cursor() as cur:
            cur.execute(
                "SELECT status FROM chat_advisory_runs WHERE id = %s",
                (run_id,),
            )
            row = cur.fetchone()
        return row[0] if row else None

    def update_session_status(self, session_token: str, status: str):
        with self._cursor(commit=True) as cur:
            cur.execute(
                """
                UPDATE chat_sessions
                SET status = %s, updated_at = NOW()
                WHERE session_token = %s
                """,
                (status, session_token),
            )
