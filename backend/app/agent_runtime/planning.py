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


def _bounded_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.65
    return max(0.0, min(1.0, number))


planning_module = PlanningModule()
