from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agent_tools.contracts import (
    AgentToolCategory,
    AgentToolDefinition,
    AgentToolPermission,
    AgentToolSpec,
)
from app.models.drawing_explanation import DrawingExplanation
from app.models.flow import ProcessFlow
from app.models.process import ProcessPlan
from app.services.export_service import ExportService


_export_service = ExportService()


def export_agent_tools() -> list[AgentToolDefinition]:
    return [
        AgentToolDefinition(
            spec=AgentToolSpec(
                name="render_process_plan_markdown",
                description="把工序方案和流程图渲染为 Markdown 文本，不落盘。",
                category=AgentToolCategory.EXPORT,
                permission=AgentToolPermission.GENERATE,
                input_schema={"process_plan": "ProcessPlan JSON", "flow": "ProcessFlow JSON"},
                output_schema={"markdown": "string"},
                model_callable=False,
                cacheable=False,
                max_runtime_seconds=10,
            ),
            handler=render_process_plan_markdown_tool,
        ),
        AgentToolDefinition(
            spec=AgentToolSpec(
                name="archive_process_plan_markdown",
                description="把工序方案和流程图导出为 Markdown 文件。",
                category=AgentToolCategory.EXPORT,
                permission=AgentToolPermission.WRITE,
                input_schema={
                    "process_plan": "ProcessPlan JSON",
                    "flow": "ProcessFlow JSON",
                    "archive_dir": "path string, default archives",
                },
                output_schema={"file_path": "string"},
                model_callable=False,
                cacheable=False,
                requires_human_confirmation=True,
                max_runtime_seconds=10,
            ),
            handler=archive_process_plan_markdown_tool,
        ),
        AgentToolDefinition(
            spec=AgentToolSpec(
                name="export_annotations",
                description="把图纸精细标注导出为 CSV 和 JSON 文件。",
                category=AgentToolCategory.EXPORT,
                permission=AgentToolPermission.WRITE,
                input_schema={
                    "explanations": "list of DrawingExplanation JSON",
                    "export_dir": "path string",
                },
                output_schema={"csv_path": "string", "json_path": "string"},
                model_callable=False,
                cacheable=False,
                requires_human_confirmation=True,
                max_runtime_seconds=20,
            ),
            handler=export_annotations_tool,
        ),
    ]


def render_process_plan_markdown_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    plan = ProcessPlan.model_validate(arguments.get("process_plan") or {})
    flow = ProcessFlow.model_validate(arguments.get("flow") or {})
    return {"markdown": _export_service.to_markdown(plan, flow)}


def archive_process_plan_markdown_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    plan = ProcessPlan.model_validate(arguments.get("process_plan") or {})
    flow = ProcessFlow.model_validate(arguments.get("flow") or {})
    archive_dir = _optional_dir(arguments.get("archive_dir") or "archives")
    file_path = _export_service.archive_markdown(plan, flow, archive_dir)
    return {"file_path": str(file_path)}


def export_annotations_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    raw_explanations = arguments.get("explanations") or []
    if not isinstance(raw_explanations, list):
        raise ValueError("explanations 必须是列表")
    export_dir = _required_dir(arguments.get("export_dir"))
    explanations = [DrawingExplanation.model_validate(item or {}) for item in raw_explanations]
    csv_path, json_path = _export_service.export_annotations(explanations, export_dir)
    return {"csv_path": str(csv_path), "json_path": str(json_path)}


def _required_dir(value: Any) -> Path:
    if not value:
        raise ValueError("缺少目录参数")
    path = Path(str(value)).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _optional_dir(value: Any) -> Path:
    path = Path(str(value)).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path
