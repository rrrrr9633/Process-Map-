from __future__ import annotations

from app.agent_runtime.state import AgentRun, AgentRunEventType, AgentRunStatus
from app.agent_tools.contracts import AgentToolCall, AgentToolPermission
from app.agent_tools.registry import AgentToolRegistry, agent_tool_registry


class ControlledAgentExecutor:
    def __init__(self, registry: AgentToolRegistry | None = None) -> None:
        self.registry = registry or agent_tool_registry

    def create_run(self, *, goal: str, input_files: list[str] | None = None) -> AgentRun:
        run = AgentRun(goal=goal, input_files=input_files or [])
        run.record_event(AgentRunEventType.RUN_CREATED, "AgentRun 已创建", {"input_files": run.input_files})
        return run

    def run_tool(
        self,
        run: AgentRun,
        tool_name: str,
        arguments: dict,
        *,
        max_permission: AgentToolPermission = AgentToolPermission.READ_ONLY,
        human_confirmed: bool = False,
    ) -> AgentRun:
        definition = self.registry.get(tool_name)
        if _permission_rank(definition.spec.permission) > _permission_rank(max_permission):
            run.status = AgentRunStatus.FAILED
            run.record_event(
                AgentRunEventType.RUN_FAILED,
                f"工具 {tool_name} 权限超过当前执行器允许范围",
                {"tool_permission": definition.spec.permission.value, "max_permission": max_permission.value},
            )
            return run
        if definition.spec.requires_human_confirmation and not human_confirmed:
            run.status = AgentRunStatus.WAITING_HUMAN
            run.current_step = tool_name
            run.record_event(
                AgentRunEventType.HUMAN_REVIEW_REQUIRED,
                f"工具 {tool_name} 需要人工确认后才能执行",
                {
                    "tool_permission": definition.spec.permission.value,
                    "max_permission": max_permission.value,
                    "requires_human_confirmation": True,
                },
            )
            return run
        run.status = AgentRunStatus.RUNNING
        run.current_step = tool_name
        call = AgentToolCall(tool_name=tool_name, arguments=arguments)
        run.record_event(AgentRunEventType.TOOL_REQUESTED, f"请求执行工具 {tool_name}", call.model_dump(mode="json"))
        observation = self.registry.call(call)
        run.record_tool_observation(call, observation)
        if observation.ok and run.status != AgentRunStatus.WAITING_HUMAN:
            run.status = AgentRunStatus.RUNNING
        return run

    def complete_run(self, run: AgentRun, final_result: dict) -> AgentRun:
        run.final_result = final_result
        run.status = AgentRunStatus.COMPLETED
        run.current_step = "completed"
        run.record_event(AgentRunEventType.RUN_COMPLETED, "AgentRun 已完成", final_result)
        return run


def _permission_rank(permission: AgentToolPermission) -> int:
    order = {
        AgentToolPermission.READ_ONLY: 1,
        AgentToolPermission.GENERATE: 2,
        AgentToolPermission.WRITE: 3,
    }
    return order[permission]


controlled_agent_executor = ControlledAgentExecutor()
