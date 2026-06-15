from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


AgentJobStatus = Literal["pending", "running", "completed", "failed"]


class AgentJob(BaseModel):
    job_id: str = Field(default_factory=lambda: uuid4().hex)
    session_id: str = ""
    status: AgentJobStatus = "pending"
    stage: str = "queued"
    message: str = "Agent 任务已创建"
    progress: int = 0
    payload: dict[str, Any] | None = None
    error: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AgentJobStore:
    def __init__(self, base_dir: str | Path = "generated/agent_jobs") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, AgentJob] = {}

    def create(self, *, session_id: str) -> AgentJob:
        job = AgentJob(session_id=session_id)
        return self.save(job)

    def get(self, job_id: str) -> AgentJob:
        if job_id in self._jobs:
            return self._jobs[job_id]
        path = self.job_path(job_id)
        if not path.exists():
            raise FileNotFoundError(job_id)
        job = AgentJob.model_validate_json(path.read_text(encoding="utf-8"))
        if job.status in {"pending", "running"}:
            job.status = "failed"
            job.stage = "failed"
            job.message = "Agent 任务已中断"
            job.error = "后端进程重启或任务执行中断，请重新发送消息"
            job.progress = 100
            return self.save(job)
        self._jobs[job_id] = job
        return job

    def save(self, job: AgentJob) -> AgentJob:
        job.updated_at = datetime.utcnow()
        self.job_dir(job.job_id).mkdir(parents=True, exist_ok=True)
        path = self.job_path(job.job_id)
        temp_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        temp_path.write_text(job.model_dump_json(indent=2), encoding="utf-8")
        os.replace(temp_path, path)
        self._jobs[job.job_id] = job
        return job

    def update(self, job_id: str, **updates: Any) -> AgentJob:
        job = self.get(job_id)
        for key, value in updates.items():
            if hasattr(job, key):
                setattr(job, key, value)
        return self.save(job)

    def complete(self, job_id: str, payload: dict[str, Any]) -> AgentJob:
        return self.update(
            job_id,
            status="completed",
            stage="completed",
            message="Agent 回复已生成",
            progress=100,
            payload=payload,
            error="",
        )

    def fail(self, job_id: str, error: str) -> AgentJob:
        return self.update(
            job_id,
            status="failed",
            stage="failed",
            message="Agent 任务失败",
            progress=100,
            error=error,
        )

    def job_dir(self, job_id: str) -> Path:
        return self.base_dir / Path(job_id).name

    def job_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "job.json"

    def list_for_session(self, session_id: str, *, limit: int = 20) -> list[AgentJob]:
        jobs: list[AgentJob] = []
        for path in self.base_dir.glob("*/job.json"):
            try:
                job = AgentJob.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if job.session_id == session_id:
                jobs.append(job)
        jobs.sort(key=lambda item: item.updated_at, reverse=True)
        return jobs[: max(1, min(limit, 100))]


agent_job_store = AgentJobStore()
