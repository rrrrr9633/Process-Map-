from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agent_tools.contracts import (
    AgentToolCategory,
    AgentToolDefinition,
    AgentToolPermission,
    AgentToolSpec,
)
from app.models.case import ProcessCase
from app.models.drawing_explanation import DrawingExplanation
from app.models.process_drawing import ProcessDrawingPlan
from app.services.process_drawing_plan_service import process_drawing_plan_service
from app.services.process_drawing_render_service import process_drawing_render_service


def process_drawing_agent_tools() -> list[AgentToolDefinition]:
    return [
        AgentToolDefinition(
            spec=AgentToolSpec(
                name="build_process_drawing_plan",
                description="根据案例、标注和最终指导生成确定性的细分工艺图草稿计划。",
                category=AgentToolCategory.PROCESS,
                permission=AgentToolPermission.GENERATE,
                input_schema={
                    "case": "ProcessCase JSON",
                    "job_id": "string, optional",
                    "explanations": "list of DrawingExplanation JSON, optional",
                    "final_guidance": "dict, optional",
                },
                output_schema={"process_drawing_plan": "ProcessDrawingPlan JSON"},
                model_callable=False,
                cacheable=False,
                max_runtime_seconds=20,
            ),
            handler=build_process_drawing_plan_tool,
        ),
        AgentToolDefinition(
            spec=AgentToolSpec(
                name="render_process_drawing_assets",
                description="把细分工艺图计划渲染为 SVG、PNG 和 JSON 文件。",
                category=AgentToolCategory.EXPORT,
                permission=AgentToolPermission.WRITE,
                input_schema={
                    "process_drawing_plan": "ProcessDrawingPlan JSON",
                    "target_dir": "path string",
                },
                output_schema={"process_drawing_plan": "ProcessDrawingPlan JSON", "asset_count": "int"},
                model_callable=False,
                cacheable=False,
                requires_human_confirmation=True,
                max_runtime_seconds=30,
            ),
            handler=render_process_drawing_assets_tool,
        ),
    ]


def build_process_drawing_plan_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    case = ProcessCase.model_validate(arguments.get("case") or {})
    raw_explanations = arguments.get("explanations") or []
    if not isinstance(raw_explanations, list):
        raise ValueError("explanations 必须是列表")
    explanations = [DrawingExplanation.model_validate(item or {}) for item in raw_explanations]
    plan = process_drawing_plan_service.build(
        case=case,
        job_id=str(arguments.get("job_id") or ""),
        explanations=explanations,
        final_guidance=arguments.get("final_guidance") if isinstance(arguments.get("final_guidance"), dict) else None,
    )
    return {
        "process_drawing_plan": plan.model_dump(mode="json"),
        "requires_human_review": plan.requires_manual_review,
    }


def render_process_drawing_assets_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    plan = ProcessDrawingPlan.model_validate(arguments.get("process_drawing_plan") or {})
    target_dir = _required_dir(arguments.get("target_dir"))
    rendered = process_drawing_render_service.render(plan, target_dir)
    asset_count = len(rendered.assets) + sum(len(sheet.assets) for sheet in rendered.sheets)
    return {
        "process_drawing_plan": rendered.model_dump(mode="json"),
        "asset_count": asset_count,
        "requires_human_review": rendered.requires_manual_review,
    }


def _required_dir(value: Any) -> Path:
    if not value:
        raise ValueError("缺少 target_dir")
    path = Path(str(value)).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path
