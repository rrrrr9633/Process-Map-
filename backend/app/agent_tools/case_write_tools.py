from __future__ import annotations

from typing import Any

from app.agent_tools.contracts import (
    AgentToolCategory,
    AgentToolDefinition,
    AgentToolPermission,
    AgentToolSpec,
)
from app.models.case import CaseQuality, CaseStatus, HumanEdit, ProcessCase
from app.services.case_service import case_service


def case_write_agent_tools() -> list[AgentToolDefinition]:
    return [
        AgentToolDefinition(
            spec=AgentToolSpec(
                name="save_case",
                description="保存或更新工艺案例到案例库；MySQL 不可用时按服务逻辑回退 JSON。",
                category=AgentToolCategory.CASE,
                permission=AgentToolPermission.WRITE,
                input_schema={"case": "ProcessCase JSON"},
                output_schema={"case_id": "string"},
                model_callable=False,
                cacheable=False,
                requires_human_confirmation=True,
                max_runtime_seconds=20,
            ),
            handler=save_case_tool,
        ),
        AgentToolDefinition(
            spec=AgentToolSpec(
                name="update_case_status",
                description="更新案例状态、质量、审核人和审核意见。",
                category=AgentToolCategory.CASE,
                permission=AgentToolPermission.WRITE,
                input_schema={
                    "case_id": "string",
                    "status": "draft|reviewed|approved|archived",
                    "quality": "poor|normal|good|excellent, optional",
                    "reviewer": "string, optional",
                    "comments": "string, optional",
                },
                output_schema={"updated": "bool"},
                model_callable=False,
                cacheable=False,
                requires_human_confirmation=True,
                max_runtime_seconds=10,
            ),
            handler=update_case_status_tool,
        ),
        AgentToolDefinition(
            spec=AgentToolSpec(
                name="add_case_human_edit",
                description="为案例追加一条人工编辑记录。",
                category=AgentToolCategory.CASE,
                permission=AgentToolPermission.WRITE,
                input_schema={"case_id": "string", "edit": "HumanEdit JSON"},
                output_schema={"updated": "bool"},
                model_callable=False,
                cacheable=False,
                requires_human_confirmation=True,
                max_runtime_seconds=10,
            ),
            handler=add_case_human_edit_tool,
        ),
        AgentToolDefinition(
            spec=AgentToolSpec(
                name="mark_case_ai_error",
                description="为案例追加 AI 错误记录，用于后续质量追踪。",
                category=AgentToolCategory.CASE,
                permission=AgentToolPermission.WRITE,
                input_schema={"case_id": "string", "error_description": "string"},
                output_schema={"updated": "bool"},
                model_callable=False,
                cacheable=False,
                requires_human_confirmation=True,
                max_runtime_seconds=10,
            ),
            handler=mark_case_ai_error_tool,
        ),
    ]


def save_case_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    case = ProcessCase.model_validate(arguments.get("case") or {})
    return {"case_id": case_service.save_case(case)}


def update_case_status_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    case_id = _required_string(arguments.get("case_id"), "case_id")
    status = CaseStatus(_required_string(arguments.get("status"), "status"))
    quality = CaseQuality(arguments["quality"]) if arguments.get("quality") else None
    updated = case_service.update_status(
        case_id=case_id,
        status=status,
        quality=quality,
        reviewer=str(arguments.get("reviewer") or "") or None,
        comments=str(arguments.get("comments") or "") or None,
    )
    return {"updated": updated, "requires_human_review": not updated}


def add_case_human_edit_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    case_id = _required_string(arguments.get("case_id"), "case_id")
    edit = HumanEdit.model_validate(arguments.get("edit") or {})
    updated = case_service.add_human_edit(case_id, edit)
    return {"updated": updated, "requires_human_review": not updated}


def mark_case_ai_error_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    case_id = _required_string(arguments.get("case_id"), "case_id")
    error_description = _required_string(arguments.get("error_description"), "error_description")
    updated = case_service.mark_ai_error(case_id, error_description)
    return {"updated": updated, "requires_human_review": True}


def _required_string(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"缺少 {field}")
    return text
