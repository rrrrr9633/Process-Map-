from __future__ import annotations

from typing import Any

from app.agent_tools.contracts import (
    AgentToolCategory,
    AgentToolDefinition,
    AgentToolPermission,
    AgentToolSpec,
)
from app.models.case import ProcessCase
from app.models.drawing_explanation import DrawingExplanation
from app.services.final_guidance_service import final_guidance_service


def final_guidance_agent_tools() -> list[AgentToolDefinition]:
    return [
        AgentToolDefinition(
            spec=AgentToolSpec(
                name="build_final_guidance",
                description="把案例、精细标注、气泡图和导出 CSV 汇总成最终工序指导单元。",
                category=AgentToolCategory.PROCESS,
                permission=AgentToolPermission.GENERATE,
                input_schema={
                    "case": "ProcessCase JSON",
                    "job_id": "string",
                    "explanations": "list of DrawingExplanation JSON",
                    "export_csv_url": "string",
                },
                output_schema={"final_guidance": "dict"},
                model_callable=False,
                cacheable=False,
                max_runtime_seconds=10,
            ),
            handler=build_final_guidance_tool,
        )
    ]


def build_final_guidance_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    case = ProcessCase.model_validate(arguments.get("case") or {})
    raw_explanations = arguments.get("explanations") or []
    if not isinstance(raw_explanations, list):
        raise ValueError("explanations 必须是列表")
    explanations = [DrawingExplanation.model_validate(item or {}) for item in raw_explanations]
    guidance = final_guidance_service.build(
        case=case,
        job_id=str(arguments.get("job_id") or ""),
        explanations=explanations,
        export_csv_url=str(arguments.get("export_csv_url") or ""),
    )
    return {
        "final_guidance": guidance,
        "requires_human_review": guidance.get("status") != "ready_for_process_review",
    }
