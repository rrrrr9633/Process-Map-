from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.models.case import CaseQuality, CaseStatus, HumanEdit, ProcessCase
from app.services.case_annotation_service import case_annotation_service
from app.services.case_service import case_service, knowledge_base_service

router = APIRouter(prefix="/cases", tags=["cases"])


class SaveCaseRequest(BaseModel):
    case: ProcessCase
    start_annotation: bool = True


class UpdateCaseStatusRequest(BaseModel):
    status: CaseStatus
    reviewer: Optional[str] = None
    comments: Optional[str] = None


class AddEditRequest(BaseModel):
    edit: HumanEdit


class MarkErrorRequest(BaseModel):
    error_description: str


class DeleteCaseResponse(BaseModel):
    deleted: bool
    deleted_files: list[str]
    retained_files: list[str]
    message: str


class SearchKnowledgeRequest(BaseModel):
    query: str
    entry_type: Optional[str] = None
    limit: int = 10


@router.post("/save")
def save_case(request: SaveCaseRequest, background_tasks: BackgroundTasks) -> dict:
    """保存工序案例；只有保存案例且存在原始图纸文件时，才启动精细标注后台任务。"""
    case_id = case_service.save_case(request.case)
    annotation_job = None
    source_files = [item for item in request.case.source_files if item.stored_name]
    if not request.start_annotation:
        return {"case_id": case_id, "message": "案例保存成功，未启动精细标注", "annotation_job": annotation_job}
    if not source_files:
        return {
            "case_id": case_id,
            "message": "案例保存成功，但没有绑定原始图纸文件，未启动精细标注",
            "annotation_job": annotation_job,
        }
    try:
        annotation_job = case_annotation_service.start_job(case_id)
        background_tasks.add_task(case_annotation_service.run_job, case_id, annotation_job["job_id"])
    except Exception as exc:
        annotation_job = {
            "status": "failed_to_start",
            "message": f"案例已保存，但精细标注启动失败：{type(exc).__name__}: {exc}",
        }
    return {"case_id": case_id, "message": "案例保存成功，已启动精细标注", "annotation_job": annotation_job}


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


@router.delete("/{case_id}", response_model=DeleteCaseResponse)
def delete_case(case_id: str) -> DeleteCaseResponse:
    """删除案例，同时清理不再被其他案例引用的 uploads 文件。"""
    result = case_service.delete_case(case_id, delete_source_files=True)
    if not result["deleted"]:
        raise HTTPException(status_code=404, detail="案例不存在")
    return DeleteCaseResponse(
        deleted=True,
        deleted_files=result["deleted_files"],
        retained_files=result["retained_files"],
        message="案例已删除",
    )


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


@router.post("/{case_id}/annotations/start")
async def start_case_annotation(case_id: str, background_tasks: BackgroundTasks) -> dict:
    """启动案例精细标注后台任务。"""
    try:
        job = case_annotation_service.start_job(case_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="案例不存在")
    background_tasks.add_task(case_annotation_service.run_job, case_id, job["job_id"])
    return job


@router.post("/{case_id}/annotation/start")
async def start_case_annotation_legacy(case_id: str, background_tasks: BackgroundTasks) -> dict:
    return await start_case_annotation(case_id, background_tasks)


@router.post("/{case_id}/annotations/retry")
async def retry_case_annotation(case_id: str, background_tasks: BackgroundTasks) -> dict:
    """重新启动案例精细标注后台任务。"""
    try:
        job = case_annotation_service.start_job(case_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="案例不存在")
    background_tasks.add_task(case_annotation_service.run_job, case_id, job["job_id"])
    return job


@router.post("/{case_id}/annotation/retry")
async def retry_case_annotation_legacy(case_id: str, background_tasks: BackgroundTasks) -> dict:
    return await retry_case_annotation(case_id, background_tasks)


@router.get("/{case_id}/annotations/status")
def get_case_annotation_status(case_id: str) -> dict:
    """获取案例精细标注最新任务状态。"""
    if not case_service.load_case(case_id):
        raise HTTPException(status_code=404, detail="案例不存在")
    job = case_annotation_service.get_latest_job(case_id)
    return job or {
        "case_id": case_id,
        "status": "not_started",
        "stage": "not_started",
        "progress": 0,
        "message": "尚未启动精细标注",
    }


@router.get("/{case_id}/annotation/status")
def get_case_annotation_status_legacy(case_id: str) -> dict:
    return get_case_annotation_status(case_id)


@router.get("/{case_id}/annotations/result")
def get_case_annotation_result(case_id: str) -> dict:
    """获取案例精细标注结果。"""
    if not case_service.load_case(case_id):
        raise HTTPException(status_code=404, detail="案例不存在")
    result = case_annotation_service.get_result(case_id)
    if not result:
        raise HTTPException(status_code=404, detail="精细标注结果不存在")
    return result


@router.get("/{case_id}/annotation/result")
def get_case_annotation_result_legacy(case_id: str) -> dict:
    return get_case_annotation_result(case_id)


@router.get("/{case_id}/annotations/assets/{job_id}/{asset_path:path}")
def get_case_annotation_asset(case_id: str, job_id: str, asset_path: str) -> FileResponse:
    """读取案例精细标注生成资源。"""
    try:
        path = case_annotation_service.resolve_asset(case_id, job_id, asset_path)
    except ValueError:
        raise HTTPException(status_code=404, detail="资源不存在")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="资源不存在")
    return FileResponse(path)


@router.get("/{case_id}/annotation/assets/{job_id}/{asset_path:path}")
def get_case_annotation_asset_legacy(case_id: str, job_id: str, asset_path: str) -> FileResponse:
    return get_case_annotation_asset(case_id, job_id, asset_path)


@router.post("/{case_id}/load-to-workbench")
def load_case_to_workbench(case_id: str) -> dict:
    """只返回案例绑定文件名，供前端复用 uploads 重新分析。"""
    case = case_service.load_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="案例不存在")
    return {
        "case_id": case.case_id,
        "case_name": case.case_name,
        "source_files": [item.model_dump(mode="json") for item in case.source_files],
    }


@router.post("/knowledge/search")
def search_knowledge(request: SearchKnowledgeRequest):
    """搜索知识库"""
    entries = knowledge_base_service.search_knowledge(
        request.query,
        request.entry_type,
        request.limit
    )
    return {"results": entries}
