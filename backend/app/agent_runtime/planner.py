from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from app.agent_runtime.action import ActionModule
from app.agent_runtime.execution_graph import AgentExecutionGraph, agent_execution_graph
from app.agent_runtime.executor import ControlledAgentExecutor
from app.agent_runtime.memory import MemoryModule
from app.agent_runtime.perception import PerceptionModule
from app.agent_runtime.planning import PlanningModule
from app.agent_runtime.reflection import ReflectionModule
from app.agent_runtime.response import ResponseModule
from app.agent_runtime.state import AgentRun, AgentRunEventType, AgentRunStatus
from app.agent_tools import init_agent_tools
from app.agent_tools.contracts import AgentToolPermission
from app.agent_tools.registry import AgentToolRegistry, agent_tool_registry


class AgentPlanner:
    def __init__(
        self,
        *,
        registry: AgentToolRegistry | None = None,
        executor: ControlledAgentExecutor | None = None,
        perception: PerceptionModule | None = None,
        memory: MemoryModule | None = None,
        planning: PlanningModule | None = None,
        action: ActionModule | None = None,
        reflection: ReflectionModule | None = None,
        response: ResponseModule | None = None,
        execution_graph: AgentExecutionGraph | None = None,
    ) -> None:
        self.registry = registry or agent_tool_registry
        self.executor = executor or ControlledAgentExecutor(self.registry)
        self.perception = perception or PerceptionModule()
        self.memory = memory or MemoryModule()
        self.planning = planning or PlanningModule()
        self.action = action or ActionModule(self.executor)
        self.reflection = reflection or ReflectionModule()
        self.response = response or ResponseModule(self.executor)
        self.execution_graph = execution_graph or agent_execution_graph

    async def run(
        self,
        *,
        goal: str,
        input_files: list[str] | None = None,
        user_message: str = "",
        max_permission: AgentToolPermission = AgentToolPermission.READ_ONLY,
        max_steps: int = 5,
        human_confirmed_tools: list[str] | None = None,
        initial_context: dict[str, Any] | None = None,
        progress_callback: Callable[[str, str, int], Awaitable[None] | None] | None = None,
    ) -> AgentRun:
        init_agent_tools()
        perception = self.perception.perceive(
            goal=goal,
            input_files=input_files or [],
            user_message=user_message,
            initial_context=initial_context,
        )
        run = self.executor.create_run(goal=goal, input_files=input_files or [])
        run.status = AgentRunStatus.PLANNING
        for warning in perception.warnings:
            run.risks.append(warning)
        run.record_event(
            AgentRunEventType.PLAN_CREATED,
            "Agent 六模块管线已启动",
            {
                "max_permission": max_permission.value,
                "max_steps": max_steps,
                "perception": perception.model_dump(mode="json"),
            },
        )

        confirmed = set(human_confirmed_tools or [])
        step_count = max(1, min(max_steps, 12))
        for step_index in range(1, step_count + 1):
            specs = self.registry.list_specs(model_callable_only=False, max_permission=max_permission)
            tool_specs = [spec.model_dump(mode="json") for spec in specs]
            memory = self.memory.build_snapshot(
                run=run,
                perception=perception.model_dump(mode="json"),
            )
            if not run.plan:
                run.plan = self.execution_graph.plan_for_intent(perception.intent, {spec["name"] for spec in tool_specs if "name" in spec})
            base_progress = 30 + int(((step_index - 1) / step_count) * 45)
            await self._emit_progress(
                progress_callback,
                "planning",
                f"Agent 正在规划第 {step_index} 步并选择工具",
                min(base_progress, 72),
            )

            try:
                decision = await self.planning.decide_next(
                    goal=goal,
                    tool_specs=tool_specs,
                    memory=memory.model_dump(mode="json"),
                    max_permission=max_permission,
                )
            except Exception as exc:
                run.status = AgentRunStatus.FAILED
                run.record_event(
                    AgentRunEventType.RUN_FAILED,
                    f"AI Planner 调用失败：{type(exc).__name__}: {exc}",
                )
                return run

            available_tool_names = {spec["name"] for spec in tool_specs if "name" in spec}
            graph_decision = self._graph_decision(
                perception=perception.model_dump(mode="json"),
                run=run,
                available_tool_names=available_tool_names,
            )
            graph_tools = {step.get("tool_name") for step in run.plan if isinstance(step, dict)}
            fallback = None
            if graph_decision and (
                decision.action != "tool"
                or self._is_repeated_successful_tool(run, decision.tool_name)
                or self._should_graph_override(perception.intent, decision.tool_name, graph_decision.tool_name, graph_tools)
            ):
                fallback = graph_decision
            elif decision.action != "tool" or self._is_repeated_successful_tool(run, decision.tool_name):
                fallback = self.planning.fallback_decision(
                    memory=memory.model_dump(mode="json"),
                    available_tool_names=available_tool_names,
                )
                if fallback:
                    decision = fallback

            run.record_event(
                AgentRunEventType.PLAN_CREATED,
                f"AI Planner 生成第 {step_index} 步动作",
                {"step": step_index, "decision": decision.model_dump(mode="json")},
            )
            if decision.plan:
                run.plan = decision.plan
            for question in decision.questions:
                if question not in run.questions:
                    run.questions.append(question)

            action_type = decision.action
            if action_type == "final":
                await self._emit_progress(
                    progress_callback,
                    "reflection",
                    "Agent 已完成判断，正在准备最终回复",
                    76,
                )
                return self.response.complete(run, decision.final_result or {"reason": decision.reason})

            if action_type != "tool":
                run.status = AgentRunStatus.FAILED
                run.record_event(
                    AgentRunEventType.RUN_FAILED,
                    "AI Planner 返回了不支持的动作",
                    {"decision": decision.model_dump(mode="json")},
                )
                return run

            tool_name = decision.tool_name
            arguments = decision.arguments
            if decision.confidence < 0.5:
                run.status = AgentRunStatus.WAITING_HUMAN
                run.record_event(
                    AgentRunEventType.HUMAN_REVIEW_REQUIRED,
                    "AI Planner 置信度不足，需要用户补充信息或确认下一步",
                    {
                        "confidence": decision.confidence,
                        "reason": decision.reason,
                        "questions": decision.questions,
                    },
                )
                return run
            if not tool_name:
                run.status = AgentRunStatus.FAILED
                run.record_event(
                    AgentRunEventType.RUN_FAILED,
                    "AI Planner 未返回 tool_name",
                    {"decision": decision.model_dump(mode="json")},
                )
                return run

            self._mark_plan_step(run, tool_name, "running")
            await self._emit_progress(
                progress_callback,
                "action",
                f"Agent 正在执行工具：{tool_name}",
                min(base_progress + 8, 74),
            )
            run = self.action.execute_tool(
                run=run,
                tool_name=tool_name,
                arguments=arguments,
                max_permission=max_permission,
                human_confirmed=tool_name in confirmed,
                perception=perception.model_dump(mode="json"),
            )
            self._mark_plan_step(run, tool_name, "done" if run.observations and run.observations[-1].ok else "skipped")
            await self._emit_progress(
                progress_callback,
                "reflection",
                f"Agent 正在检查工具结果：{tool_name}",
                min(base_progress + 14, 78),
            )
            reflection = self.reflection.inspect_after_action(run)
            run.record_event(
                AgentRunEventType.OBSERVATION_RECORDED,
                "Reflection 模块完成结果检查",
                {"reflection": reflection.model_dump(mode="json")},
            )
            if not reflection.should_continue:
                return run

        run.status = AgentRunStatus.WAITING_HUMAN
        run.record_event(
            AgentRunEventType.HUMAN_REVIEW_REQUIRED,
            "AI Planner 达到最大自动步数，需要人工确认下一步",
            {"max_steps": max_steps, "fallback_result": self.response.fallback_result(run)},
        )
        return run

    def _graph_decision(
        self,
        *,
        perception: dict[str, Any],
        run: AgentRun,
        available_tool_names: set[str],
    ):
        latest_outputs = self.action._latest_outputs(run)
        step = self.execution_graph.next_step(
            intent=str(perception.get("intent") or ""),
            run=run,
            latest_outputs=latest_outputs,
            available_tool_names=available_tool_names,
        )
        if not step:
            return None
        from app.agent_runtime.planning import AgentPlanDecision

        arguments: dict[str, Any] = {}
        if step.tool_name == "search_cases":
            arguments["query"] = _query_from_perception_and_outputs(perception, latest_outputs)
            arguments["limit"] = 5
        return AgentPlanDecision(
            intent=str(perception.get("intent") or "general_chat"),
            plan=self.execution_graph.plan_for_intent(str(perception.get("intent") or ""), available_tool_names),
            action="tool",
            tool_name=step.tool_name,
            arguments=arguments,
            confidence=0.78,
            reason=f"执行图推进：{step.purpose}",
        )

    async def _emit_progress(
        self,
        progress_callback: Callable[[str, str, int], Awaitable[None] | None] | None,
        stage: str,
        message: str,
        progress: int,
    ) -> None:
        if not progress_callback:
            return
        try:
            result = progress_callback(stage, message, progress)
            if inspect.isawaitable(result):
                await result
        except Exception:
            return

    def _mark_plan_step(self, run: AgentRun, tool_name: str, status: str) -> None:
        for step in run.plan:
            if step.get("tool_name") == tool_name and step.get("status") in {None, "", "pending", "running"}:
                step["status"] = status
                return

    def _is_repeated_successful_tool(self, run: AgentRun, tool_name: str) -> bool:
        if not tool_name:
            return False
        return any(observation.tool_name == tool_name and observation.ok for observation in run.observations)

    def _should_graph_override(self, intent: str, decision_tool: str, graph_tool: str, graph_tools: set[str]) -> bool:
        if intent not in {"process_generation", "export", "case_management"}:
            return False
        if not graph_tool or graph_tool == decision_tool:
            return False
        if decision_tool and decision_tool not in graph_tools:
            return False
        return True


agent_planner = AgentPlanner()


def _query_from_perception_and_outputs(perception: dict[str, Any], latest_outputs: dict[str, Any]) -> str:
    parse_result = latest_outputs.get("parse_result") if isinstance(latest_outputs.get("parse_result"), dict) else {}
    part = parse_result.get("part") if isinstance(parse_result.get("part"), dict) else {}
    return " ".join(
        str(item)
        for item in [
            perception.get("goal"),
            perception.get("user_message"),
            part.get("part_name"),
            part.get("material"),
            part.get("heat_treatment"),
        ]
        if item
    )
