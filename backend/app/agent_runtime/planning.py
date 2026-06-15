from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agent_tools.contracts import AgentToolPermission
from app.services.ai_service import ai_service


class AgentPlanDecision(BaseModel):
    intent: str = "general_chat"
    plan: list[dict[str, Any]] = Field(default_factory=list)
    action: str
    tool_name: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)
    final_result: dict[str, Any] = Field(default_factory=dict)
    stop_condition: str = ""
    confidence: float = 0.0
    questions: list[str] = Field(default_factory=list)
    reason: str = ""


class PlanningModule:
    async def decide_next(
        self,
        *,
        goal: str,
        tool_specs: list[dict[str, Any]],
        memory: dict[str, Any],
        max_permission: AgentToolPermission,
    ) -> AgentPlanDecision:
        raw = await ai_service.plan_agent_next_action(
            goal=goal,
            tool_specs=tool_specs,
            observations=[memory],
            max_permission=max_permission.value,
        )
        action = str(raw.get("action") or "").strip().lower()
        arguments = raw.get("arguments") if isinstance(raw.get("arguments"), dict) else {}
        final_result = raw.get("final_result") if isinstance(raw.get("final_result"), dict) else {}
        plan = raw.get("plan") if isinstance(raw.get("plan"), list) else []
        questions = raw.get("questions") if isinstance(raw.get("questions"), list) else []
        return AgentPlanDecision(
            intent=str(raw.get("intent") or "general_chat"),
            plan=[item for item in plan if isinstance(item, dict)][:6],
            action=action,
            tool_name=str(raw.get("tool_name") or "").strip(),
            arguments=arguments,
            final_result=final_result,
            stop_condition=str(raw.get("stop_condition") or ""),
            confidence=_bounded_confidence(raw.get("confidence")),
            questions=[str(item) for item in questions if item][:6],
            reason=str(raw.get("reason") or ""),
        )

    def fallback_decision(
        self,
        *,
        memory: dict[str, Any],
        available_tool_names: set[str],
    ) -> AgentPlanDecision | None:
        short_term = memory.get("short_term") if isinstance(memory, dict) else {}
        if not isinstance(short_term, dict):
            return None
        perception = short_term.get("perception") if isinstance(short_term.get("perception"), dict) else {}
        observations = short_term.get("recent_observations") if isinstance(short_term.get("recent_observations"), list) else []
        last_run = short_term.get("last_run") if isinstance(short_term.get("last_run"), dict) else {}
        recommended = perception.get("recommended_tools") if isinstance(perception.get("recommended_tools"), list) else []
        called = {
            str(item.get("tool_name"))
            for item in observations
            if isinstance(item, dict) and item.get("tool_name")
        }
        latest_outputs = _latest_outputs(observations) or _latest_outputs_from_last_run(last_run)
        has_process_goal = str(perception.get("intent") or "") == "process_generation"

        if "parse_drawing" in available_tool_names and "parse_drawing" in recommended and "parse_drawing" not in called:
            return AgentPlanDecision(
                intent=str(perception.get("intent") or "drawing_analysis"),
                plan=[{"step_no": 1, "title": "解析输入图纸", "purpose": "先获得结构化图纸信息", "tool_name": "parse_drawing", "status": "pending"}],
                action="tool",
                tool_name="parse_drawing",
                arguments={},
                confidence=0.75,
                reason="Planner 未给出可执行动作，按感知模块推荐先解析图纸。",
            )
        if (
            has_process_goal
            and "generate_rule_process_plan" in available_tool_names
            and latest_outputs.get("parse_result")
            and "generate_rule_process_plan" not in called
        ):
            return AgentPlanDecision(
                intent="process_generation",
                plan=[{"step_no": 2, "title": "生成规则工序", "purpose": "基于解析结果生成可校验工序方案", "tool_name": "generate_rule_process_plan", "status": "pending"}],
                action="tool",
                tool_name="generate_rule_process_plan",
                arguments={"mode": "standard_8"},
                confidence=0.7,
                reason="已有图纸解析结果，继续生成规则工序。",
            )
        if (
            has_process_goal
            and "validate_process_plan" in available_tool_names
            and latest_outputs.get("parse_result")
            and latest_outputs.get("process_plan")
            and "validate_process_plan" not in called
        ):
            return AgentPlanDecision(
                intent="process_generation",
                plan=[{"step_no": 3, "title": "校验工序方案", "purpose": "检查工序是否覆盖图纸风险和关键要求", "tool_name": "validate_process_plan", "status": "pending"}],
                action="tool",
                tool_name="validate_process_plan",
                arguments={},
                confidence=0.72,
                reason="已有解析结果和工序方案，继续做规则校验。",
            )
        if observations:
            return AgentPlanDecision(
                intent=str(perception.get("intent") or "general_chat"),
                plan=[],
                action="final",
                final_result=_final_result_from_observations(observations),
                confidence=0.7,
                reason="已获得可用工具结果，输出本轮汇总。",
            )
        if latest_outputs:
            return AgentPlanDecision(
                intent=str(perception.get("intent") or "general_chat"),
                plan=[],
                action="final",
                final_result=_final_result_from_outputs(latest_outputs),
                confidence=0.7,
                reason="根据会话中的上一轮 Agent 结果回答用户追问。",
            )
        if str(perception.get("intent") or "") == "general_chat" and perception.get("user_message"):
            return AgentPlanDecision(
                intent="general_chat",
                plan=[],
                action="final",
                final_result={
                    "summary": "我已经收到你的问题。你可以继续描述要分析的图纸、工序目标或上传文件，我会根据上下文继续处理。",
                    "assistant_message": "我已经收到你的问题。你可以继续描述要分析的图纸、工序目标或上传文件，我会根据上下文继续处理。",
                },
                confidence=0.7,
                reason="普通对话无需调用工具。",
            )
        return None


def _bounded_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.65
    return max(0.0, min(1.0, number))


def _latest_outputs(observations: list[Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for item in observations:
        if not isinstance(item, dict) or not item.get("ok"):
            continue
        output = item.get("output") if isinstance(item.get("output"), dict) else {}
        for key in (
            "parse_result",
            "process_plan",
            "flow",
            "validation_issues",
            "process_guidance",
            "annotation_result",
        ):
            if key in output:
                values[key] = output[key]
    return values


def _final_result_from_observations(observations: list[Any]) -> dict[str, Any]:
    latest = _latest_outputs(observations)
    tool_names = [
        str(item.get("tool_name"))
        for item in observations
        if isinstance(item, dict) and item.get("tool_name")
    ]
    summary_parts: list[str] = []
    if latest.get("parse_result"):
        summary_parts.append("已完成图纸解析")
    if latest.get("process_plan"):
        summary_parts.append("已生成规则工序方案")
    if "validation_issues" in latest:
        issues = latest.get("validation_issues") or []
        summary_parts.append(f"已完成工序校验，发现 {len(issues) if isinstance(issues, list) else 0} 项需关注内容")
    if not summary_parts:
        summary_parts.append("已完成可执行工具调用")
    return {
        "summary": "，".join(summary_parts) + "。",
        "tool_names": tool_names,
        "latest_outputs": latest,
    }


def _latest_outputs_from_last_run(last_run: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    final_result = last_run.get("run", {}).get("final_result") if isinstance(last_run.get("run"), dict) else {}
    if isinstance(final_result, dict) and isinstance(final_result.get("latest_outputs"), dict):
        values.update(final_result["latest_outputs"])
    last_observation = last_run.get("last_observation") if isinstance(last_run.get("last_observation"), dict) else {}
    output = last_observation.get("output") if isinstance(last_observation.get("output"), dict) else {}
    values.update(output)
    return values


def _final_result_from_outputs(latest: dict[str, Any]) -> dict[str, Any]:
    summary_parts: list[str] = []
    if latest.get("parse_result"):
        summary_parts.append("我会基于上一轮图纸解析结果继续回答")
    if latest.get("process_plan"):
        summary_parts.append("上一轮已有工序方案，可继续解释工序顺序、风险或导出结果")
    if "validation_issues" in latest:
        issues = latest.get("validation_issues") or []
        summary_parts.append(f"当前记录中有 {len(issues) if isinstance(issues, list) else 0} 项校验问题")
    return {
        "summary": "；".join(summary_parts) + "。",
        "latest_outputs": latest,
    }


planning_module = PlanningModule()
