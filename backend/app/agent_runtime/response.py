from __future__ import annotations

from typing import Any

from app.agent_runtime.executor import ControlledAgentExecutor
from app.agent_runtime.state import AgentRun, AgentRunStatus


class ResponseModule:
    def __init__(self, executor: ControlledAgentExecutor | None = None) -> None:
        self.executor = executor or ControlledAgentExecutor()

    def complete(self, run: AgentRun, final_result: dict[str, Any]) -> AgentRun:
        return self.executor.complete_run(run, final_result)

    def fallback_result(self, run: AgentRun) -> dict[str, Any]:
        return {
            "status": run.status.value,
            "summary": "Agent 运行已停止，等待人工处理或下一轮用户输入。",
            "observations": [item.model_dump(mode="json") for item in run.observations[-3:]],
            "questions": run.questions[-8:],
            "risks": run.risks[-8:],
        }

    def to_chat_response(self, run: AgentRun) -> dict[str, Any]:
        last_observation = run.observations[-1] if run.observations else None
        final_result = run.final_result or {}
        assistant_message = self._assistant_message(run, final_result)
        actions = self._next_actions(run)
        cards = self._cards(run, final_result)
        return {
            "run": run.model_dump(mode="json"),
            "assistant_message": assistant_message,
            "status": run.status.value,
            "cards": cards,
            "actions": actions,
            "tool_trace": [
                {
                    "tool_name": call.tool_name,
                    "arguments": call.arguments,
                    "ok": observation.ok if index < len(run.observations) else None,
                    "elapsed_ms": observation.elapsed_ms if index < len(run.observations) else 0,
                }
                for index, call in enumerate(run.tool_calls)
                for observation in [run.observations[index] if index < len(run.observations) else None]
            ],
            "last_observation": last_observation.model_dump(mode="json") if last_observation else None,
        }

    def _assistant_message(self, run: AgentRun, final_result: dict[str, Any]) -> str:
        if final_result.get("assistant_message"):
            return str(final_result["assistant_message"])
        if run.status == AgentRunStatus.COMPLETED:
            if final_result:
                summary = final_result.get("summary") or final_result.get("answer") or final_result.get("message")
                if summary:
                    return str(summary)
            return "已完成本轮 Agent 分析。"
        if run.status == AgentRunStatus.WAITING_HUMAN:
            pending_call = self._pending_call(run)
            tool_name = pending_call.get("tool_name") or run.current_step or "下一步工具"
            if pending_call:
                return f"我已经规划好下一步，需要你确认后执行工具：{tool_name}。确认后我会继续处理。"
            if run.observations:
                observation = run.observations[-1]
                if observation.requires_human_review:
                    return (
                        f"我已完成工具调用：{observation.tool_name}。结果包含需要人工复核的风险项，"
                        "请查看下方详情；你可以补充要求让我继续分析，或切换到固定分析流程。"
                    )
            if run.questions:
                return "我还需要你补充信息：" + "；".join(run.questions[-3:])
            return "当前结果需要人工确认后继续。"
        if run.status == AgentRunStatus.FAILED:
            event_message = run.events[-1].message if run.events else "Agent 运行失败。"
            return event_message
        if run.observations:
            observation = run.observations[-1]
            if observation.ok:
                return f"我已完成工具调用：{observation.tool_name}。结果已整理在下方详情中，你可以继续追问或让我进入下一步。"
            return f"工具 {observation.tool_name} 执行失败：{observation.error_message or '未返回可用结果'}"
        return "Agent 已接收任务，正在等待下一步。"

    def _next_actions(self, run: AgentRun) -> list[dict[str, Any]]:
        if run.status == AgentRunStatus.WAITING_HUMAN:
            pending_call = self._pending_call(run)
            if not pending_call:
                return [
                    {"type": "ask_followup", "label": "继续追问"},
                    {"type": "revise_request", "label": "补充需求"},
                ]
            tool_name = pending_call.get("tool_name") or run.current_step or ""
            return [
                {
                    "type": "confirm_tool",
                    "label": "确认继续执行",
                    "tool_name": tool_name,
                    "arguments": pending_call.get("arguments", {}),
                    "requires_human_confirmation": True,
                },
                {"type": "revise_request", "label": "修改需求"},
            ]
        if run.status == AgentRunStatus.COMPLETED:
            return [{"type": "ask_followup", "label": "继续追问"}]
        if run.status == AgentRunStatus.FAILED:
            return [{"type": "retry", "label": "调整后重试"}]
        return []

    def _pending_call(self, run: AgentRun) -> dict[str, Any]:
        for event in reversed(run.events):
            pending_call = event.payload.get("pending_call") if isinstance(event.payload, dict) else None
            if isinstance(pending_call, dict):
                return pending_call
        return {}

    def _cards(self, run: AgentRun, final_result: dict[str, Any]) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        if run.risks:
            cards.append({"kind": "risks", "title": "风险提示", "items": run.risks[-6:]})
        if run.questions:
            cards.append({"kind": "questions", "title": "需要确认", "items": run.questions[-6:]})
        if run.plan:
            cards.append({"kind": "plan", "title": "Agent 计划", "items": run.plan[-6:]})
        if final_result:
            cards.append({"kind": "final_result", "title": "结构化结果", "content": final_result})
        if run.observations:
            observation = run.observations[-1]
            preview = observation.output
            cards.append(
                {
                    "kind": "last_tool",
                    "title": f"最后工具：{observation.tool_name}",
                    "ok": observation.ok,
                    "content": preview,
                }
            )
        return cards


response_module = ResponseModule()
