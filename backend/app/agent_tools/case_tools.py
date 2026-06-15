from __future__ import annotations

from typing import Any

from app.agent_tools.contracts import (
    AgentToolCategory,
    AgentToolDefinition,
    AgentToolPermission,
    AgentToolSpec,
)
from app.models.case import CaseQuality, CaseStatus
from app.services.case_service import case_service


def case_agent_tools() -> list[AgentToolDefinition]:
    return [
        AgentToolDefinition(
            spec=AgentToolSpec(
                name="search_cases",
                description="按当前案例库条件检索历史案例；当前为基础检索，后续可升级向量检索。",
                category=AgentToolCategory.CASE,
                permission=AgentToolPermission.READ_ONLY,
                input_schema={"query": "string, optional", "status": "draft|reviewed|approved|archived, optional", "quality": "optional", "limit": "int"},
                output_schema={"cases": "list of case summaries", "memories": "similar long-term memory entries"},
                model_callable=True,
                cacheable=False,
                max_runtime_seconds=10,
            ),
            handler=search_cases_tool,
        ),
        AgentToolDefinition(
            spec=AgentToolSpec(
                name="load_case_summary",
                description="读取单个案例的摘要、工序和图纸绑定文件，不返回大字段全文。",
                category=AgentToolCategory.CASE,
                permission=AgentToolPermission.READ_ONLY,
                input_schema={"case_id": "string"},
                output_schema={"case": "case summary"},
                model_callable=True,
                cacheable=False,
                max_runtime_seconds=10,
            ),
            handler=load_case_summary_tool,
        ),
    ]


def search_cases_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    status = _optional_enum(CaseStatus, arguments.get("status"))
    quality = _optional_enum(CaseQuality, arguments.get("quality"))
    limit = max(1, min(50, int(arguments.get("limit") or 10)))
    query = str(arguments.get("query") or "").strip()
    memories = case_service.search_similar_memories(query, limit=limit) if query else []
    memory_case_ids = [str(item.get("case_id")) for item in memories if item.get("case_id")]
    loaded_cases = [case for case_id in memory_case_ids for case in [case_service.load_case(case_id)] if case]
    fallback_cases = case_service.list_cases(status=status, quality=quality, limit=limit)
    seen: set[str] = set()
    cases = []
    for case in [*loaded_cases, *fallback_cases]:
        if case.case_id in seen:
            continue
        seen.add(case.case_id)
        cases.append(case)
        if len(cases) >= limit:
            break
    return {
        "cases": [
            {
                "case_id": case.case_id,
                "case_name": case.case_name,
                "status": case.status.value,
                "quality": case.quality.value if case.quality else None,
                "tags": case.tags,
                "operation_count": len(case.process_plan.operations),
                "source_files": [item.model_dump(mode="json") for item in case.source_files],
                "updated_at": case.updated_at.isoformat(),
            }
            for case in cases
        ],
        "memories": [
            {
                "memory_id": item.get("memory_id"),
                "kind": item.get("kind"),
                "case_id": item.get("case_id"),
                "title": item.get("title"),
                "score": item.get("score"),
                "quality": item.get("quality"),
                "ai_error_count": item.get("ai_error_count"),
                "human_edit_count": item.get("human_edit_count"),
            }
            for item in memories
        ],
    }


def load_case_summary_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    case_id = str(arguments.get("case_id") or "").strip()
    if not case_id:
        raise ValueError("缺少 case_id")
    case = case_service.load_case(case_id)
    if not case:
        raise FileNotFoundError(case_id)
    return {
        "case": {
            "case_id": case.case_id,
            "case_name": case.case_name,
            "status": case.status.value,
            "quality": case.quality.value if case.quality else None,
            "part": case.drawing_parse_result.part.model_dump(mode="json"),
            "source_files": [item.model_dump(mode="json") for item in case.source_files],
            "operations": [
                {
                    "operation_no": operation.operation_no,
                    "operation_name": operation.operation_name,
                    "operation_type": operation.operation_type.value,
                    "targets": operation.targets,
                    "control_points": operation.control_points,
                    "inspection_items": operation.inspection_items,
                    "drawing_basis": operation.drawing_basis,
                }
                for operation in case.process_plan.operations
            ],
            "risk_count": len(case.drawing_parse_result.risk_flags),
            "ai_error_count": len(case.ai_errors),
            "human_edit_count": len(case.human_edits),
        },
        "requires_human_review": bool(case.ai_errors or case.drawing_parse_result.risk_flags),
    }


def _optional_enum(enum_type, value):
    if value in (None, ""):
        return None
    return enum_type(value)
