from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.models.drawing_explanation import DrawingExplanation, JobStage, ProcessJob


class JobService:
    def __init__(self, base_dir: str | Path = "generated/jobs") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_job(self, files: list[str]) -> ProcessJob:
        job = ProcessJob(job_id=uuid4().hex, files=files)
        self.job_dir(job.job_id).mkdir(parents=True, exist_ok=True)
        self.pages_dir(job.job_id).mkdir(parents=True, exist_ok=True)
        self.bubbles_dir(job.job_id).mkdir(parents=True, exist_ok=True)
        self.exports_dir(job.job_id).mkdir(parents=True, exist_ok=True)
        self.save(job)
        return job

    def get(self, job_id: str) -> ProcessJob:
        path = self.job_path(job_id)
        if not path.exists():
            raise FileNotFoundError(job_id)
        return ProcessJob.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, job: ProcessJob) -> ProcessJob:
        job.updated_at = datetime.utcnow().isoformat()
        self.job_dir(job.job_id).mkdir(parents=True, exist_ok=True)
        self.job_path(job.job_id).write_text(job.model_dump_json(indent=2), encoding="utf-8")
        return job

    def update(
        self,
        job_id: str,
        *,
        stage: JobStage | None = None,
        status: str | None = None,
        progress: int | None = None,
        message: str | None = None,
        error: str | None = None,
        ai_stream_preview: str | None = None,
        ai_stream_chunks: int | None = None,
    ) -> ProcessJob:
        job = self.get(job_id)
        if stage is not None:
            job.stage = stage
        if status is not None:
            job.status = status  # type: ignore[assignment]
        if progress is not None:
            job.progress = max(0, min(100, progress))
        if message is not None:
            job.message = message
        if error is not None:
            job.error = error
        if ai_stream_preview is not None:
            job.ai_stream_preview = ai_stream_preview[-2000:]
        if ai_stream_chunks is not None:
            job.ai_stream_chunks = max(0, ai_stream_chunks)
        return self.save(job)

    def set_explanations(self, job_id: str, explanations: list[DrawingExplanation]) -> ProcessJob:
        job = self.get(job_id)
        job.explanations = explanations
        return self.save(job)

    def set_process_result(self, job_id: str, result: dict) -> ProcessJob:
        job = self.get(job_id)
        job.process_result = result
        return self.save(job)

    def fail(self, job_id: str, error: str) -> ProcessJob:
        return self.update(job_id, stage="failed", status="failed", progress=100, message="任务失败", error=error)

    def complete(self, job_id: str) -> ProcessJob:
        return self.update(job_id, stage="completed", status="completed", progress=100, message="任务完成")

    def job_dir(self, job_id: str) -> Path:
        return self.base_dir / job_id

    def pages_dir(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "pages"

    def bubbles_dir(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "bubbles"

    def exports_dir(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "exports"

    def job_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "job.json"

    def resolve_asset(self, job_id: str, relative_path: str) -> Path:
        base = self.job_dir(job_id).resolve()
        target = (base / relative_path).resolve()
        if base not in target.parents and target != base:
            raise ValueError("非法资源路径")
        return target


job_service = JobService()