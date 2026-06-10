from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.drawing import DrawingParseResult
from app.models.process import ProcessPlan


class CaseStatus(str, Enum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    ARCHIVED = "archived"


class CaseQuality(str, Enum):
    POOR = "poor"
    NORMAL = "normal"
    GOOD = "good"
    EXCELLENT = "excellent"


class CaseSourceFile(BaseModel):
    """uploads 目录中已存图纸，用于案例加载后跳过重复上传"""

    stored_name: str
    original_name: str = ""


class HumanEdit(BaseModel):
    """人工编辑记录"""

    field: str
    original_value: str
    edited_value: str
    reason: Optional[str] = None
    editor: Optional[str] = None
    edit_time: datetime = Field(default_factory=datetime.now)


class ProcessCase(BaseModel):
    """工序案例"""

    case_id: str
    case_name: str
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    drawing_parse_result: DrawingParseResult
    source_files: List[CaseSourceFile] = Field(default_factory=list)
    external_conditions: Optional[dict] = None
    generation_ai_response: Optional[dict] = None

    process_plan: ProcessPlan

    human_edits: List[HumanEdit] = Field(default_factory=list)
    ai_errors: List[str] = Field(default_factory=list)

    status: CaseStatus = CaseStatus.DRAFT
    quality: Optional[CaseQuality] = None

    creator: Optional[str] = None
    reviewer: Optional[str] = None
    review_comments: Optional[str] = None
    tags: List[str] = Field(default_factory=list)

    production_feedback: Optional[str] = None
    actual_duration: Optional[float] = None
    quality_issues: List[str] = Field(default_factory=list)


class KnowledgeEntry(BaseModel):
    """知识库条目"""

    entry_id: str
    entry_type: str
    title: str
    content: str
    source_case_ids: List[str] = Field(default_factory=list)
    confidence: float = 1.0
    usage_count: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    tags: List[str] = Field(default_factory=list)
