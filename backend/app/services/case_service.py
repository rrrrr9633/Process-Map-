from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from app.config import settings
from app.models.case import CaseQuality, CaseStatus, HumanEdit, KnowledgeEntry, ProcessCase


class CaseService:
    """案例管理服务"""
    
    def __init__(self):
        self.storage_path = settings.knowledge_base_path / "cases"
        self.storage_path.mkdir(exist_ok=True, parents=True)
    
    def save_case(self, case: ProcessCase) -> str:
        """保存案例"""
        case.updated_at = datetime.now()
        file_path = self.storage_path / f"{case.case_id}.json"
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(case.model_dump(mode="json"), f, ensure_ascii=False, indent=2)
        
        return case.case_id
    
    def load_case(self, case_id: str) -> Optional[ProcessCase]:
        """加载案例"""
        file_path = self.storage_path / f"{case_id}.json"
        
        if not file_path.exists():
            return None
        
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return ProcessCase(**data)

    def delete_case(self, case_id: str, *, delete_source_files: bool = True) -> dict:
        """删除案例，并按需清理该案例绑定的 uploads 文件。"""
        case = self.load_case(case_id)
        if not case:
            return {"deleted": False, "deleted_files": [], "retained_files": []}

        deleted_files: list[str] = []
        retained_files: list[str] = []
        file_path = self.storage_path / f"{case_id}.json"
        referenced_names = {item.stored_name for item in case.source_files if item.stored_name}

        if file_path.exists():
            file_path.unlink()
            deleted_files.append(str(file_path))

        if delete_source_files and referenced_names:
            still_referenced = self._referenced_source_file_names()
            upload_root = Path("./uploads").resolve()
            for stored_name in referenced_names:
                if stored_name in still_referenced:
                    retained_files.append(stored_name)
                    continue
                source_path = (upload_root / Path(stored_name).name).resolve()
                if upload_root not in source_path.parents or not source_path.is_file():
                    continue
                source_path.unlink()
                deleted_files.append(str(source_path))

        return {
            "deleted": True,
            "deleted_files": deleted_files,
            "retained_files": retained_files,
        }

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
        limit: int = 50
    ) -> List[ProcessCase]:
        """列出案例"""
        cases = []
        
        for file_path in self.storage_path.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    case = ProcessCase(**data)
                    
                    # 过滤条件
                    if status and case.status != status:
                        continue
                    if quality and case.quality != quality:
                        continue
                    if tags and not any(tag in case.tags for tag in tags):
                        continue
                    
                    cases.append(case)
                    
                    if len(cases) >= limit:
                        break
            except Exception:
                continue
        
        # 按更新时间倒序
        cases.sort(key=lambda c: c.updated_at, reverse=True)
        return cases
    
    def add_human_edit(self, case_id: str, edit: HumanEdit) -> bool:
        """添加人工编辑记录"""
        case = self.load_case(case_id)
        if not case:
            return False
        
        case.human_edits.append(edit)
        case.updated_at = datetime.now()
        self.save_case(case)
        return True
    
    def mark_ai_error(self, case_id: str, error_description: str) -> bool:
        """标记AI错误"""
        case = self.load_case(case_id)
        if not case:
            return False
        
        case.ai_errors.append(error_description)
        case.updated_at = datetime.now()
        self.save_case(case)
        return True
    
    def update_status(self, case_id: str, status: CaseStatus, reviewer: Optional[str] = None, comments: Optional[str] = None) -> bool:
        """更新案例状态"""
        case = self.load_case(case_id)
        if not case:
            return False
        
        case.status = status
        if reviewer:
            case.reviewer = reviewer
        if comments:
            case.review_comments = comments
        case.updated_at = datetime.now()
        
        self.save_case(case)
        return True
    
    def get_similar_cases(self, drawing_info: dict, limit: int = 5) -> List[ProcessCase]:
        """获取相似案例"""
        # TODO: 实现基于图纸特征的相似度匹配
        # 可以考虑：
        # - 零件类型
        # - 加工特征
        # - 技术要求
        # - 尺寸范围
        
        return self.list_cases(status=CaseStatus.APPROVED, limit=limit)


class KnowledgeBaseService:
    """知识库服务"""
    
    def __init__(self):
        self.storage_path = settings.knowledge_base_path / "knowledge"
        self.storage_path.mkdir(exist_ok=True, parents=True)
    
    def save_entry(self, entry: KnowledgeEntry) -> str:
        """保存知识条目"""
        file_path = self.storage_path / f"{entry.entry_id}.json"
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(entry.model_dump(mode="json"), f, ensure_ascii=False, indent=2)
        
        return entry.entry_id
    
    def load_entry(self, entry_id: str) -> Optional[KnowledgeEntry]:
        """加载知识条目"""
        file_path = self.storage_path / f"{entry_id}.json"
        
        if not file_path.exists():
            return None
        
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return KnowledgeEntry(**data)
    
    def search_knowledge(self, query: str, entry_type: Optional[str] = None, limit: int = 10) -> List[KnowledgeEntry]:
        """搜索知识库"""
        entries = []
        
        for file_path in self.storage_path.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    entry = KnowledgeEntry(**data)
                    
                    # 过滤类型
                    if entry_type and entry.entry_type != entry_type:
                        continue
                    
                    # 简单的关键词匹配
                    if query.lower() in entry.title.lower() or query.lower() in entry.content.lower():
                        entries.append(entry)
                    
                    if len(entries) >= limit:
                        break
            except Exception:
                continue
        
        # 按置信度和使用次数排序
        entries.sort(key=lambda e: (e.confidence, e.usage_count), reverse=True)
        return entries
    
    def extract_knowledge_from_cases(self, cases: List[ProcessCase]) -> List[KnowledgeEntry]:
        """从案例中提取知识"""
        # TODO: 实现知识提取逻辑
        # 可以提取：
        # - 常见的人工修改模式
        # - 高频的技术要求组合
        # - 设备选择偏好
        # - 工序顺序优化
        
        return []


# 全局实例
case_service = CaseService()
knowledge_base_service = KnowledgeBaseService()
