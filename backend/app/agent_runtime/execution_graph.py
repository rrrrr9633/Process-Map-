from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agent_runtime.state import AgentRun


@dataclass(frozen=True)
class GraphStep:
    tool_name: str
    title: str
    purpose: str


class AgentExecutionGraph:
    PROCESS_GRAPH = [
        GraphStep("parse_drawing", "解析图纸", "建立结构化图纸证据"),
        GraphStep("search_cases", "召回历史经验", "从长期记忆中找到相似案例和修正经验"),
        GraphStep("generate_rule_process_plan", "生成工序方案", "基于图纸证据和规则生成工艺路线"),
        GraphStep("validate_process_plan", "校验工序方案", "检查覆盖性、风险和人工复核点"),
        GraphStep("build_process_guidance", "生成工艺指导", "把工序方案转成工艺人员能执行的指导"),
    ]

    EXPORT_GRAPH = [
        GraphStep("render_process_plan_markdown", "生成导出预览", "先生成不落盘文本供确认"),
        GraphStep("archive_process_plan_markdown", "归档导出文件", "用户确认后落盘导出"),
    ]

    CASE_GRAPH = [
        GraphStep("search_cases", "检索案例", "先检查现有案例和长期记忆"),
        GraphStep("save_case", "保存案例", "用户确认后写入案例库"),
    ]

    def next_step(
        self,
        *,
        intent: str,
        run: AgentRun,
        latest_outputs: dict[str, Any],
        available_tool_names: set[str],
    ) -> GraphStep | None:
        graph = self._graph_for_intent(intent)
        if not graph:
            return None
        called = {observation.tool_name for observation in run.observations if observation.ok}
        for step in graph:
            if step.tool_name not in available_tool_names or step.tool_name in called:
                continue
            if not self._requirements_met(step.tool_name, latest_outputs, run):
                continue
            return step
        return None

    def plan_for_intent(self, intent: str, available_tool_names: set[str]) -> list[dict[str, Any]]:
        graph = self._graph_for_intent(intent)
        return [
            {
                "step_no": index + 1,
                "title": step.title,
                "purpose": step.purpose,
                "tool_name": step.tool_name,
                "status": "pending",
            }
            for index, step in enumerate(graph)
            if step.tool_name in available_tool_names
        ][:6]

    def _graph_for_intent(self, intent: str) -> list[GraphStep]:
        if intent == "process_generation":
            return self.PROCESS_GRAPH
        if intent == "export":
            return self.EXPORT_GRAPH
        if intent == "case_management":
            return self.CASE_GRAPH
        return []

    def _requirements_met(self, tool_name: str, latest_outputs: dict[str, Any], run: AgentRun) -> bool:
        if tool_name == "parse_drawing":
            return bool(run.input_files)
        if tool_name == "search_cases":
            return True
        if tool_name == "generate_rule_process_plan":
            return bool(latest_outputs.get("parse_result"))
        if tool_name == "validate_process_plan":
            return bool(latest_outputs.get("parse_result") and latest_outputs.get("process_plan"))
        if tool_name == "build_process_guidance":
            return bool(latest_outputs.get("parse_result") and latest_outputs.get("process_plan"))
        if tool_name in {"render_process_plan_markdown", "archive_process_plan_markdown"}:
            return bool(latest_outputs.get("process_plan"))
        if tool_name == "save_case":
            return bool(latest_outputs.get("case"))
        return True


agent_execution_graph = AgentExecutionGraph()
