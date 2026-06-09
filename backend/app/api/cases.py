from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models.case import CaseQuality, CaseStatus, HumanEdit, ProcessCase
from app.services.case_service import case_service, knowledge_base_service

router = APIRouter(prefix="/cases", tags=["cases"])


class SaveCaseRequest(BaseModel):
    case: ProcessCase


class UpdateCaseStatusRequest(BaseModel):
    status: CaseStatus
    reviewer: Optional[str] = None
    comments: Optional[str] = None


class AddEditRequest(BaseModel):
    edit: HumanEdit


class MarkErrorRequest(BaseModel):
    error_description: str


class SearchKnowledgeRequest(BaseModel):
    query: str
    entry_type: Optional[str] = None
    limit: int = 10


@router.post("/save")
def save_case(request: SaveCaseRequest) -> dict:
    """保存工序案例"""
    case_id = case_service.save_case(request.case)
    return {"case_id": case_id, "message": "案例保存成功"}


@router.get("/list")
def list_cases(
    status: Optional[CaseStatus] = None,
    quality: Optional[CaseQuality] = None,
    limit: int = 50
) -> List[ProcessCase]:
    """列出案例"""
    return case_service.list_cases(status=status, quality=quality, limit=limit)


@router.get("/{case_id}")
def get_case(case_id: str) -> ProcessCase:
    """获取案例详情"""
    case = case_service.load_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="案例不存在")
    return case


@router.post("/{case_id}/edit")
def add_edit(case_id: str, request: AddEditRequest) -> dict:
    """添加人工编辑记录"""
    success = case_service.add_human_edit(case_id, request.edit)
    if not success:
        raise HTTPException(status_code=404, detail="案例不存在")
    return {"message": "编辑记录已添加"}


@router.post("/{case_id}/mark-error")
def mark_error(case_id: str, request: MarkErrorRequest) -> dict:
    """标记AI错误"""
    success = case_service.mark_ai_error(case_id, request.error_description)
    if not success:
        raise HTTPException(status_code=404, detail="案例不存在")
    return {"message": "错误已标记"}


@router.post("/{case_id}/status")
def update_status(case_id: str, request: UpdateCaseStatusRequest) -> dict:
    """更新案例状态"""
    success = case_service.update_status(
        case_id,
        request.status,
        request.reviewer,
        request.comments
    )
    if not success:
        raise HTTPException(status_code=404, detail="案例不存在")
    return {"message": "状态已更新"}


@router.get("/{case_id}/similar")
def get_similar_cases(case_id: str, limit: int = 5) -> List[ProcessCase]:
    """获取相似案例"""
    case = case_service.load_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="案例不存在")
    
    # TODO: 实现更智能的相似度匹配
    drawing_info = case.drawing_parse_result.model_dump()
    return case_service.get_similar_cases(drawing_info, limit)


@router.post("/knowledge/search")
def search_knowledge(request: SearchKnowledgeRequest):
    """搜索知识库"""
    entries = knowledge_base_service.search_knowledge(
        request.query,
        request.entry_type,
        request.limit
    )
    return {"results": entries}
