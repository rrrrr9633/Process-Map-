from __future__ import annotations

import json
import traceback
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from app.db import CaseAnnotationJobRecord, CaseAnnotationResultRecord, SessionLocal
from app.models.drawing_explanation import DrawingExplanation
from app.services.bubble_diagram_service import bubble_diagram_service
from app.services.case_service import BACKEND_DIR, case_service
from app.services.drawing_explanation_service import drawing_explanation_service
from app.services.export_service import ExportService


UPLOADS_DIR = BACKEND_DIR / "uploads"
ANNOTATION_ROOT = BACKEND_DIR / "generated" / "case_annotations"


class CaseAnnotationService:
    def __init__(self) -> None:
        self.export_service = ExportService()
        ANNOTATION_ROOT.mkdir(parents=True, exist_ok=True)

    def start_job(self, case_id: str) -> dict:
        case = case_service.load_case(case_id)
        if not case:
            raise FileNotFoundError(case_id)
        job_id = uuid4().hex
        record = CaseAnnotationJobRecord(
            job_id=job_id,
            case_id=case_id,
            status="pending",
            stage="queued",
            progress=0,
            message="等待开始精细标注",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        with SessionLocal() as session:
            session.add(record)
            session.commit()
        return self.job_to_dict(record)

    async def run_job(self, case_id: str, job_id: str) -> None:
        completed = 0
        stage = "queued"
        try:
            case = case_service.load_case(case_id)
            if not case:
                raise FileNotFoundError(f"案例不存在：{case_id}")
            paths = self._resolve_case_paths(case)
            if not paths:
                raise RuntimeError("案例没有绑定可复用的 uploads 图纸文件")

            total = len(paths)
            self.update_job(
                job_id,
                status="running",
                stage="rendering",
                progress=5,
                message=f"精细标注已启动：共 {total} 份图纸",
            )

            explanations: list[DrawingExplanation] = []
            for index, path in enumerate(paths, start=1):
                stage = "explaining"

                def on_stream_delta(delta: str, chunk_count: int, content: str, file_index=index) -> None:
                    self.update_job(
                        job_id,
                        status="running",
                        stage="explaining",
                        progress=min(80, 10 + int((file_index - 1) / total * 60) + chunk_count // 25),
                        message=f"第 {file_index}/{total} 份图纸 AI 图解中，已接收 {chunk_count} 段内容",
                        ai_stream_preview=content,
                        ai_stream_chunks=chunk_count,
                    )

                self.update_job(
                    job_id,
                    status="running",
                    stage="explaining",
                    progress=10 + int((index - 1) / total * 60),
                    message=f"正在精细图解第 {index}/{total} 份图纸：{path.name}",
                    ai_stream_preview="AI 精细标注请求已发出，正在等待模型返回内容",
                    ai_stream_chunks=0,
                )
                explanation = await drawing_explanation_service.explain_file(
                    path,
                    self.pages_dir(case_id, job_id),
                    index,
                    on_stream_delta=on_stream_delta,
                )
                explanations.append(explanation)
                completed = index
                self.update_job(
                    job_id,
                    status="running",
                    stage="explaining",
                    progress=10 + int(index / total * 60),
                    message=f"已完成 {index}/{total} 份图纸精细图解",
                )

            stage = "bubble_generating"
            self.update_job(
                job_id,
                status="running",
                stage="bubble_generating",
                progress=85,
                message="正在生成气泡图和标注导出数据",
            )
            explanations = [
                bubble_diagram_service.generate(explanation, self.bubbles_dir(case_id, job_id))
                for explanation in explanations
            ]
            csv_path, _ = self.export_service.export_annotations(explanations, self.exports_dir(case_id, job_id))
            for explanation in explanations:
                for page_explanation in explanation.page_explanations:
                    if page_explanation.bubble_asset:
                        page_explanation.bubble_asset.export_csv_path = str(csv_path)
                        page_explanation.bubble_asset.export_csv_url = f"exports/{csv_path.name}"
                if explanation.bubble_asset:
                    explanation.bubble_asset.export_csv_path = str(csv_path)
                    explanation.bubble_asset.export_csv_url = f"exports/{csv_path.name}"

            self.save_result(case_id, job_id, explanations, f"exports/{csv_path.name}")
            self.update_job(
                job_id,
                status="completed",
                stage="completed",
                progress=100,
                message="精细标注完成",
                ai_stream_preview="",
            )
        except Exception as exc:
            self.update_job(
                job_id,
                status="failed",
                stage="failed",
                progress=100,
                message="精细标注失败",
                error_type=type(exc).__name__,
                error_message=str(exc),
                error_detail=(
                    f"失败阶段：{stage}；已完成图纸：{completed}；"
                    f"异常详情：{traceback.format_exc()}"
                ),
            )

    def get_latest_job(self, case_id: str) -> dict | None:
        with SessionLocal() as session:
            record = (
                session.query(CaseAnnotationJobRecord)
                .filter(CaseAnnotationJobRecord.case_id == case_id)
                .order_by(CaseAnnotationJobRecord.updated_at.desc())
                .first()
            )
            return self.job_to_dict(record) if record else None

    def get_job(self, job_id: str) -> dict | None:
        with SessionLocal() as session:
            record = session.get(CaseAnnotationJobRecord, job_id)
            return self.job_to_dict(record) if record else None

    def get_result(self, case_id: str) -> dict | None:
        with SessionLocal() as session:
            record = session.get(CaseAnnotationResultRecord, case_id)
            if not record:
                return None
            return {
                "case_id": record.case_id,
                "job_id": record.job_id,
                "explanations": json.loads(record.explanations_json),
                "export_csv_url": record.export_csv_url,
                "updated_at": record.updated_at.isoformat(),
            }

    def save_result(
        self,
        case_id: str,
        job_id: str,
        explanations: list[DrawingExplanation],
        export_csv_url: str,
    ) -> None:
        payload = json.dumps([item.model_dump(mode="json") for item in explanations], ensure_ascii=False)
        with SessionLocal() as session:
            record = session.get(CaseAnnotationResultRecord, case_id)
            if record:
                record.job_id = job_id
                record.explanations_json = payload
                record.export_csv_url = export_csv_url
                record.updated_at = datetime.utcnow()
            else:
                session.add(
                    CaseAnnotationResultRecord(
                        case_id=case_id,
                        job_id=job_id,
                        explanations_json=payload,
                        export_csv_url=export_csv_url,
                        updated_at=datetime.utcnow(),
                    )
                )
            session.commit()

    def update_job(self, job_id: str, **updates) -> None:
        try:
            with SessionLocal() as session:
                record = session.get(CaseAnnotationJobRecord, job_id)
                if not record:
                    return
                for key, value in updates.items():
                    if value is None:
                        continue
                    if key == "ai_stream_preview":
                        value = str(value)[-3000:]
                    setattr(record, key, value)
                record.updated_at = datetime.utcnow()
                session.commit()
        except SQLAlchemyError as exc:
            print(f"[case-annotation] update failed: {type(exc).__name__}: {exc}", flush=True)

    def job_to_dict(self, record: CaseAnnotationJobRecord) -> dict:
        return {
            "job_id": record.job_id,
            "case_id": record.case_id,
            "status": record.status,
            "stage": record.stage,
            "progress": record.progress,
            "message": record.message,
            "ai_stream_preview": record.ai_stream_preview,
            "ai_stream_chunks": record.ai_stream_chunks,
            "error_type": record.error_type,
            "error_message": record.error_message,
            "error_detail": record.error_detail,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
        }

    def _resolve_case_paths(self, case) -> list[Path]:
        upload_root = UPLOADS_DIR.resolve()
        paths: list[Path] = []
        for source_file in case.source_files:
            if not source_file.stored_name:
                continue
            path = (upload_root / Path(source_file.stored_name).name).resolve()
            if upload_root not in path.parents or not path.is_file():
                continue
            paths.append(path)
        return paths

    def base_dir(self, case_id: str, job_id: str) -> Path:
        return ANNOTATION_ROOT / case_id / job_id

    def pages_dir(self, case_id: str, job_id: str) -> Path:
        path = self.base_dir(case_id, job_id) / "pages"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def bubbles_dir(self, case_id: str, job_id: str) -> Path:
        path = self.base_dir(case_id, job_id) / "bubbles"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def exports_dir(self, case_id: str, job_id: str) -> Path:
        path = self.base_dir(case_id, job_id) / "exports"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def resolve_asset(self, case_id: str, job_id: str, relative_path: str) -> Path:
        base = self.base_dir(case_id, job_id).resolve()
        target = (base / relative_path).resolve()
        if base not in target.parents and target != base:
            raise ValueError("非法资源路径")
        return target


case_annotation_service = CaseAnnotationService()