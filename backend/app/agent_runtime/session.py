from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class AgentSessionMessage(BaseModel):
    role: str
    content: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentSession(BaseModel):
    session_id: str = Field(default_factory=lambda: uuid4().hex)
    title: str = "Agent 会话"
    messages: list[AgentSessionMessage] = Field(default_factory=list)
    uploaded_files: list[dict[str, Any]] = Field(default_factory=list)
    last_run: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AgentSessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, AgentSession] = {}

    def get_or_create(self, session_id: str | None = None, *, title: str = "Agent 会话") -> AgentSession:
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        session = AgentSession(session_id=session_id or uuid4().hex, title=title)
        self._sessions[session.session_id] = session
        return session

    def append_message(
        self,
        session: AgentSession,
        *,
        role: str,
        content: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        session.messages.append(AgentSessionMessage(role=role, content=content, payload=payload or {}))
        session.messages = session.messages[-30:]
        session.updated_at = datetime.utcnow()

    def add_files(self, session: AgentSession, files: list[dict[str, Any]]) -> None:
        existing = {item.get("file_path") for item in session.uploaded_files}
        for file in files:
            if file.get("file_path") not in existing:
                session.uploaded_files.append(file)
        session.uploaded_files = session.uploaded_files[-20:]
        session.updated_at = datetime.utcnow()

    def set_last_run(self, session: AgentSession, run_payload: dict[str, Any]) -> None:
        session.last_run = run_payload
        session.updated_at = datetime.utcnow()

    def public_dict(self, session: AgentSession) -> dict[str, Any]:
        return session.model_dump(mode="json")


agent_session_store = AgentSessionStore()
