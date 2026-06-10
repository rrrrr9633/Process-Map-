from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.db import CaseRecord, SessionLocal
from app.models.case import CaseQuality, CaseSourceFile, CaseStatus, HumanEdit, KnowledgeEntry, ProcessCase
from app.models.drawing import DrawingParseResult
from app.models.process import ProcessPlan


BACKEND_DIR = Path(__file__).resolve().parents[2]
UPLOADS_DIR = BACKEND_DIR / "uploads"


def _json(value, default=None) -> str:
    return json.dumps(value if value is not None else default, ensure_ascii=False)


def _loads(text: str | None, default):
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


class CaseService:
    """案例管理服务：MySQL 优先，旧 JSON 文件只作为兼容读取来源。"""

    def __init__(self):
        self.storage_path = settings.knowledge_base_path / "cases"
        self.storage_path.mkdir(exist_ok=True, parents=True)

    def save_case(self, case: ProcessCase) -> str:
        case.updated_at = datetime.now()
        record = self._case_to_record(case)
        try:
            with SessionLocal() as session:
                existing = session.get(CaseRecord, case.case_id)
                if existing:
                    self._copy_record(record, existing)
                else:
                    session.add(record)
                session.commit()
            return case.case_id
        except SQLAlchemyError as exc:
            raise RuntimeError(f"案例写入 MySQL 失败：{type(exc).__name__}: {exc}") from exc

    def load_case(self, case_id: str) -> Optional[ProcessCase]:
        try:
            with SessionLocal() as session:
                record = session.get(CaseRecord, case_id)
                if record:
                    return self._record_to_case(record)
        except SQLAlchemyError:
            pass
        return self._load_legacy_json_case(case_id)

    def delete_case(self, case_id: str, *, delete_source_files: bool = True) -> dict:
        case = self.load_case(case_id)
        if not case:
            return {"deleted": False, "deleted_files": [], "retained_files": []}

        deleted_files: list[str] = []
        retained_files: list[str] = []
        referenced_names = {item.stored_name for item in case.source_files if item.stored_name}

        try:
            with SessionLocal() as session:
                record = session.get(CaseRecord, case_id)
                if record:
                    session.delete(record)
                    session.commit()
        except SQLAlchemyError as exc:
            raise RuntimeError(f"案例删除 MySQL 记录失败：{type(exc).__name__}: {exc}") from exc

        legacy_path = self.storage_path / f"{case_id}.json"
        if legacy_path.exists():
            legacy_path.unlink()
            deleted_files.append(str(legacy_path))

        if delete_source_files and referenced_names:
            still_referenced = self._referenced_source_file_names()
            upload_root = UPLOADS_DIR.resolve()
            for stored_name in referenced_names:
                if stored_name in still_referenced:
                    retained_files.append(stored_name)
                    continue
                source_path = (upload_root / Path(stored_name).name).resolve()
                if upload_root not in source_path.parents or not source_path.is_file():
                    continue
                source_path.unlink()
                deleted_files.append(str(source_path))

        return {"deleted": True, "deleted_files": deleted_files, "retained_files": retained_files}

    def _referenced_source_file_names(self) -> set[str]:
        names: set[str] = set()
        for case in self.list_cases(limit=10000):
            for source_file in case.source_files:
                if source_file.stored_name:
                    names.add(source_file.stored_name)
        return names

    def list_cases(
        self,
        status: Optional[CaseStatus] = None,
        quality: Optional[CaseQuality] = None,
        tags: Optional[List[str]] = None,
        limit: int = 50,
    ) -> List[ProcessCase]:
        cases: list[ProcessCase] = []
        try:
            with SessionLocal() as session:
                query = session.query(CaseRecord)
                if status:
                    query = query.filter(CaseRecord.status == status.value)
                if quality:
                    query = query.filter(CaseRecord.quality == quality.value)
                records = query.order_by(CaseRecord.updated_at.desc()).limit(limit).all()
                cases = [self._record_to_case(record) for record in records]
        except SQLAlchemyError:
            cases = []

        if not cases:
            cases = self._list_legacy_json_cases(status=status, quality=quality, tags=tags, limit=limit)
        if tags:
            cases = [case for case in cases if any(tag in case.tags for tag in tags)]
        return cases[:limit]

    def add_human_edit(self, case_id: str, edit: HumanEdit) -> bool:
        case = self.load_case(case_id)
        if not case:
            return False
        case.human_edits.append(edit)
        self.save_case(case)
        return True

    def mark_ai_error(self, case_id: str, error_description: str) -> bool:
        case = self.load_case(case_id)
        if not case:
            return False
        case.ai_errors.append(error_description)
        self.save_case(case)
        return True

    def update_status(
        self,
        case_id: str,
        status: CaseStatus,
        quality: Optional[CaseQuality] = None,
        reviewer: Optional[str] = None,
        comments: Optional[str] = None,
    ) -> bool:
        case = self.load_case(case_id)
        if not case:
            return False
        case.status = status
        case.quality = quality
        if reviewer:
            case.reviewer = reviewer
        if comments:
            case.review_comments = comments
        self.save_case(case)
        return True

    def get_similar_cases(self, drawing_info: dict, limit: int = 5) -> List[ProcessCase]:
        return self.list_cases(status=CaseStatus.APPROVED, limit=limit)

    def _case_to_record(self, case: ProcessCase) -> CaseRecord:
        return CaseRecord(
            case_id=case.case_id,
            case_name=case.case_name,
            drawing_parse_result_json=case.drawing_parse_result.model_dump_json(),
            process_plan_json=case.process_plan.model_dump_json(),
            source_files_json=_json([item.model_dump(mode="json") for item in case.source_files], []),
            external_conditions_json=_json(case.external_conditions) if case.external_conditions is not None else None,
            generation_ai_response_json=_json(case.generation_ai_response) if case.generation_ai_response is not None else None,
            human_edits_json=_json([item.model_dump(mode="json") for item in case.human_edits], []),
            ai_errors_json=_json(case.ai_errors, []),
            status=case.status.value,
            quality=case.quality.value if case.quality else None,
            creator=case.creator,
            reviewer=case.reviewer,
            review_comments=case.review_comments,
            tags_json=_json(case.tags, []),
            production_feedback=case.production_feedback,
            actual_duration=str(case.actual_duration) if case.actual_duration is not None else None,
            quality_issues_json=_json(case.quality_issues, []),
            created_at=case.created_at,
            updated_at=case.updated_at,
        )

    def _copy_record(self, source: CaseRecord, target: CaseRecord) -> None:
        for key in (
            "case_name", "drawing_parse_result_json", "process_plan_json", "source_files_json",
            "external_conditions_json", "generation_ai_response_json", "human_edits_json", "ai_errors_json",
            "status", "quality", "creator", "reviewer", "review_comments", "tags_json", "production_feedback",
            "actual_duration", "quality_issues_json", "created_at", "updated_at",
        ):
            setattr(target, key, getattr(source, key))

    def _record_to_case(self, record: CaseRecord) -> ProcessCase:
        return ProcessCase(
            case_id=record.case_id,
            case_name=record.case_name,
            created_at=record.created_at,
            updated_at=record.updated_at,
            drawing_parse_result=DrawingParseResult.model_validate_json(record.drawing_parse_result_json),
            source_files=[CaseSourceFile.model_validate(item) for item in _loads(record.source_files_json, [])],
            external_conditions=_loads(record.external_conditions_json, None),
            generation_ai_response=_loads(record.generation_ai_response_json, None),
            process_plan=ProcessPlan.model_validate_json(record.process_plan_json),
            human_edits=[HumanEdit.model_validate(item) for item in _loads(record.human_edits_json, [])],
            ai_errors=_loads(record.ai_errors_json, []),
            status=CaseStatus(record.status),
            quality=CaseQuality(record.quality) if record.quality else None,
            creator=record.creator,
            reviewer=record.reviewer,
            review_comments=record.review_comments,
            tags=_loads(record.tags_json, []),
            production_feedback=record.production_feedback,
            actual_duration=float(record.actual_duration) if record.actual_duration else None,
            quality_issues=_loads(record.quality_issues_json, []),
        )

    def _load_legacy_json_case(self, case_id: str) -> Optional[ProcessCase]:
        file_path = self.storage_path / f"{case_id}.json"
        if not file_path.exists():
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            return ProcessCase(**json.load(f))

    def _list_legacy_json_cases(
        self,
        status: Optional[CaseStatus] = None,
        quality: Optional[CaseQuality] = None,
        tags: Optional[List[str]] = None,
        limit: int = 50,
    ) -> List[ProcessCase]:
        cases: list[ProcessCase] = []
        for file_path in self.storage_path.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    case = ProcessCase(**json.load(f))
                if status and case.status != status:
                    continue
                if quality and case.quality != quality:
                    continue
                if tags and not any(tag in case.tags for tag in tags):
                    continue
                cases.append(case)
            except Exception:
                continue
        cases.sort(key=lambda c: c.updated_at, reverse=True)
        return cases[:limit]


class KnowledgeBaseService:
    def __init__(self):
        self.storage_path = settings.knowledge_base_path / "knowledge"
        self.storage_path.mkdir(exist_ok=True, parents=True)

    def save_entry(self, entry: KnowledgeEntry) -> str:
        file_path = self.storage_path / f"{entry.entry_id}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(entry.model_dump(mode="json"), f, ensure_ascii=False, indent=2)
        return entry.entry_id

    def load_entry(self, entry_id: str) -> Optional[KnowledgeEntry]:
        file_path = self.storage_path / f"{entry_id}.json"
        if not file_path.exists():
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            return KnowledgeEntry(**json.load(f))

    def search_knowledge(self, query: str, entry_type: Optional[str] = None, limit: int = 10) -> List[KnowledgeEntry]:
        entries: list[KnowledgeEntry] = []
        for file_path in self.storage_path.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    entry = KnowledgeEntry(**json.load(f))
                if entry_type and entry.entry_type != entry_type:
                    continue
                if query.lower() in entry.title.lower() or query.lower() in entry.content.lower():
                    entries.append(entry)
                if len(entries) >= limit:
                    break
            except Exception:
                continue
        entries.sort(key=lambda e: (e.confidence, e.usage_count), reverse=True)
        return entries

    def extract_knowledge_from_cases(self, cases: List[ProcessCase]) -> List[KnowledgeEntry]:
        return []


case_service = CaseService()
knowledge_base_service = KnowledgeBaseService()
