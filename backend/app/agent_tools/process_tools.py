from __future__ import annotations

from typing import Any

from app.agent_tools.contracts import (
    AgentToolCategory,
    AgentToolDefinition,
    AgentToolPermission,
    AgentToolSpec,
)
from app.models.annotation import DrawingAnnotationResult
from app.models.drawing import DrawingParseResult
from app.models.process import ProcessMode, ProcessPlan
from app.services.flow_builder import FlowBuilder
from app.services.process_generator import ProcessGenerator
from app.services.process_guidance_service import process_guidance_service
from app.services.process_validator import ProcessValidator


_generator = ProcessGenerator()
_validator = ProcessValidator()
_flow_builder = FlowBuilder()


def process_agent_tools() -> list[AgentToolDefinition]:
    return [
        AgentToolDefinition(
            spec=AgentToolSpec(
                name="generate_rule_process_plan",
                description="基于本地规则从图纸解析结果生成工序方案，不调用大模型。",
                category=AgentToolCategory.PROCESS,
                permission=AgentToolPermission.GENERATE,
                input_schema={"parse_result": "DrawingParseResult JSON", "mode": "standard_8|detailed_10"},
                output_schema={"process_plan": "ProcessPlan JSON", "flow": "ProcessFlow JSON"},
                model_callable=False,
                cacheable=False,
                max_runtime_seconds=20,
            ),
            handler=generate_rule_process_plan_tool,
        ),
        AgentToolDefinition(
            spec=AgentToolSpec(
                name="validate_process_plan",
                description="校验工序方案是否覆盖图纸触发的关键要求和风险。",
                category=AgentToolCategory.PROCESS,
                permission=AgentToolPermission.READ_ONLY,
                input_schema={"parse_result": "DrawingParseResult JSON", "process_plan": "ProcessPlan JSON"},
                output_schema={"validation_issues": "list", "requires_human_review": "bool"},
                model_callable=True,
                cacheable=False,
                max_runtime_seconds=10,
            ),
            handler=validate_process_plan_tool,
        ),
        AgentToolDefinition(
            spec=AgentToolSpec(
                name="build_process_guidance",
                description="把图纸解析、标注和工序方案合成面向工艺人员的指导结构。",
                category=AgentToolCategory.PROCESS,
                permission=AgentToolPermission.GENERATE,
                input_schema={
                    "parse_result": "DrawingParseResult JSON",
                    "annotation_result": "DrawingAnnotationResult JSON, optional",
                    "process_plan": "ProcessPlan JSON",
                },
                output_schema={"process_guidance": "ProcessGuidance JSON"},
                model_callable=False,
                cacheable=False,
                max_runtime_seconds=10,
            ),
            handler=build_process_guidance_tool,
        ),
    ]


def generate_rule_process_plan_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    parse_result = DrawingParseResult.model_validate(arguments.get("parse_result") or {})
    mode = ProcessMode(arguments.get("mode") or ProcessMode.STANDARD_8.value)
    plan = _generator.generate(parse_result, mode, external_conditions=arguments.get("external_conditions"))
    flow = _flow_builder.build(plan)
    return {
        "process_plan": plan.model_dump(mode="json"),
        "flow": flow.model_dump(mode="json"),
        "requires_human_review": plan.requires_manual_review,
    }


def validate_process_plan_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    parse_result = DrawingParseResult.model_validate(arguments.get("parse_result") or {})
    process_plan = ProcessPlan.model_validate(arguments.get("process_plan") or {})
    issues = _validator.validate(parse_result, process_plan)
    return {
        "validation_issues": [issue.model_dump(mode="json") for issue in issues],
        "requires_human_review": bool(issues),
    }


def build_process_guidance_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    parse_result = DrawingParseResult.model_validate(arguments.get("parse_result") or {})
    process_plan = ProcessPlan.model_validate(arguments.get("process_plan") or {})
    annotation_result = DrawingAnnotationResult.model_validate(arguments.get("annotation_result") or {})
    guidance = process_guidance_service.build(
        parse_result=parse_result,
        annotation_result=annotation_result,
        process_plan=process_plan,
    )
    return {
        "process_guidance": guidance.model_dump(mode="json"),
        "requires_human_review": bool(guidance.manual_review or guidance.issues),
    }