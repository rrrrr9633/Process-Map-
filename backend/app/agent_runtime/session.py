from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
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
    def __init__(self, base_dir: str | Path = "generated/agent_sessions") -> None:
        self._sessions: dict[str, AgentSession] = {}
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_or_create(self, session_id: str | None = None, *, title: str = "Agent 会话") -> AgentSession:
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        if session_id:
            loaded = self._load(session_id)
            if loaded:
                self._sessions[loaded.session_id] = loaded
                return loaded
        session = AgentSession(session_id=session_id or uuid4().hex, title=title)
        return self._save(session)

    def append_message(
        self,
        session: AgentSession,
        *,
        role: str,
        content: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        session.messages.append(AgentSessionMessage(role=role, content=content, payload=payload or {}))
        if session.title == "Agent 会话" and role == "user" and content.strip():
            session.title = content.strip().splitlines()[0][:40]
        session.messages = session.messages[-30:]
        session.updated_at = datetime.utcnow()
        self._save(session)

    def add_files(self, session: AgentSession, files: list[dict[str, Any]]) -> None:
        existing = {item.get("file_path") for item in session.uploaded_files}
        for file in files:
            if file.get("file_path") not in existing:
                session.uploaded_files.append(file)
        session.uploaded_files = session.uploaded_files[-20:]
        session.updated_at = datetime.utcnow()
        self._save(session)

    def set_last_run(self, session: AgentSession, run_payload: dict[str, Any]) -> None:
        session.last_run = run_payload
        session.updated_at = datetime.utcnow()
        self._save(session)

    def list_sessions(self, *, limit: int = 50) -> list[AgentSession]:
        sessions = {session_id: session for session_id, session in self._sessions.items()}
        for path in self.base_dir.glob("*/session.json"):
            loaded = self._load(path.parent.name)
            if loaded:
                sessions[loaded.session_id] = loaded
        values = list(sessions.values())
        values.sort(key=lambda item: item.updated_at, reverse=True)
        return values[: max(1, min(limit, 200))]

    def delete_session(self, session_id: str) -> bool:
        self._sessions.pop(session_id, None)
        path = self._session_path(session_id)
        if not path.exists():
            return False
        path.unlink()
        try:
            path.parent.rmdir()
        except OSError:
            pass
        return True

    def public_dict(self, session: AgentSession) -> dict[str, Any]:
        return session.model_dump(mode="json")

    def summary_dict(self, session: AgentSession) -> dict[str, Any]:
        last_message = session.messages[-1] if session.messages else None
        return {
            "session_id": session.session_id,
            "title": session.title,
            "message_count": len(session.messages),
            "file_count": len(session.uploaded_files),
            "last_message": last_message.content[:120] if last_message else "",
            "last_role": last_message.role if last_message else "",
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
        }

    def _save(self, session: AgentSession) -> AgentSession:
        self._session_dir(session.session_id).mkdir(parents=True, exist_ok=True)
        path = self._session_path(session.session_id)
        temp_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        temp_path.write_text(session.model_dump_json(indent=2), encoding="utf-8")
        os.replace(temp_path, path)
        self._sessions[session.session_id] = session
        return session

    def _load(self, session_id: str) -> AgentSession | None:
        path = self._session_path(session_id)
        if not path.exists():
            return None
        try:
            return AgentSession.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _session_dir(self, session_id: str) -> Path:
        return self.base_dir / Path(session_id).name

    def _session_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "session.json"


agent_session_store = AgentSessionStore()
