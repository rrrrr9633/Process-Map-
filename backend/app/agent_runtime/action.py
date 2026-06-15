from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agent_runtime.executor import ControlledAgentExecutor
from app.agent_runtime.state import AgentRun
from app.agent_tools.contracts import AgentToolPermission


class ActionModule:
    def __init__(self, executor: ControlledAgentExecutor | None = None) -> None:
        self.executor = executor or ControlledAgentExecutor()

    def execute_tool(
        self,
        *,
        run: AgentRun,
        tool_name: str,
        arguments: dict,
        max_permission: AgentToolPermission,
        human_confirmed: bool,
        perception: dict[str, Any] | None = None,
    ) -> AgentRun:
        prepared_arguments = self.prepare_arguments(
            tool_name=tool_name,
            arguments=arguments,
            run=run,
            perception=perception or {},
        )
        return self.executor.run_tool(
            run,
            tool_name,
            prepared_arguments,
            max_permission=max_permission,
            human_confirmed=human_confirmed,
        )

    def prepare_arguments(
        self,
        *,
        tool_name: str,
        arguments: dict,
        run: AgentRun,
        perception: dict[str, Any],
    ) -> dict:
        prepared = dict(arguments or {})
        normalized = perception.get("normalized_inputs") if isinstance(perception, dict) else {}
        if not isinstance(normalized, dict):
            normalized = {}
        input_files = perception.get("input_files") if isinstance(perception, dict) else []
        if not isinstance(input_files, list):
            input_files = []

        if "file_path" not in prepared:
            file_path = normalized.get("file_path") or (input_files[0] if input_files else "")
            if file_path and tool_name in {
                "parse_drawing",
                "render_drawing_pages",
                "analyze_3d_geometry",
                "render_cad_preview",
            }:
                prepared["file_path"] = file_path

        if "target_dir" not in prepared and tool_name in {"render_drawing_pages", "render_cad_preview"}:
            prepared["target_dir"] = self._default_target_dir(run, "agent_pages")
        if "target_dir" not in prepared and tool_name == "render_process_drawing_assets":
            prepared["target_dir"] = self._default_target_dir(run, "process_drawings")
        if "export_dir" not in prepared and tool_name == "export_annotations":
            prepared["export_dir"] = self._default_target_dir(run, "exports")
        return prepared

    def _default_target_dir(self, run: AgentRun, leaf: str) -> str:
        base = Path("generated") / "agent_runs" / run.run_id / leaf
        return str(base)


action_module = ActionModule()
