from __future__ import annotations

from pydantic import BaseModel, Field

from app.agent_runtime.state import AgentRun, AgentRunStatus


class ReflectionResult(BaseModel):
    should_continue: bool = True
    requires_human: bool = False
    issues: list[str] = Field(default_factory=list)


class ReflectionModule:
    def inspect_after_action(self, run: AgentRun) -> ReflectionResult:
        if run.status == AgentRunStatus.FAILED:
            return ReflectionResult(should_continue=False, requires_human=True, issues=["工具执行失败"])
        if run.status == AgentRunStatus.WAITING_HUMAN:
            return ReflectionResult(should_continue=False, requires_human=True, issues=["需要人工确认或复核"])
        if run.observations and not run.observations[-1].ok:
            return ReflectionResult(
                should_continue=False,
                requires_human=True,
                issues=[run.observations[-1].error_message or "工具返回失败"],
            )
        return ReflectionResult()


reflection_module = ReflectionModule()
