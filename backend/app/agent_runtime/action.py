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

        latest_outputs = self._latest_outputs(run)
        if tool_name in {
            "generate_rule_process_plan",
            "validate_process_plan",
            "build_process_guidance",
            "build_final_guidance",
            "build_process_drawing_plan",
        }:
            prepared.setdefault("parse_result", latest_outputs.get("parse_result"))
        if tool_name in {
            "validate_process_plan",
            "build_process_guidance",
            "render_process_plan_markdown",
            "archive_process_plan_markdown",
        }:
            prepared.setdefault("process_plan", latest_outputs.get("process_plan"))
        if tool_name in {"render_process_plan_markdown", "archive_process_plan_markdown"}:
            prepared.setdefault("flow", latest_outputs.get("flow") or {})
        if tool_name == "build_process_guidance":
            prepared.setdefault("annotation_result", latest_outputs.get("annotation_result") or {})
        if tool_name in {"normalize_annotations", "map_view_annotations_to_page", "rebuild_annotation_export_rows"}:
            prepared.setdefault("annotation_result", latest_outputs.get("annotation_result") or {})
        if tool_name == "merge_annotation_results":
            prepared.setdefault("annotation_results", [latest_outputs.get("annotation_result")] if latest_outputs.get("annotation_result") else [])
        if tool_name in {"build_final_guidance", "build_process_drawing_plan"}:
            prepared.setdefault("case", latest_outputs.get("case") or {})
            prepared.setdefault("explanations", latest_outputs.get("explanations") or [])
        if tool_name == "build_final_guidance":
            prepared.setdefault("job_id", run.run_id)
            prepared.setdefault("export_csv_url", latest_outputs.get("csv_path") or "")
        if tool_name == "build_process_drawing_plan":
            prepared.setdefault("job_id", run.run_id)
            prepared.setdefault("final_guidance", latest_outputs.get("final_guidance") or {})
        if tool_name == "render_process_drawing_assets":
            prepared.setdefault("process_drawing_plan", latest_outputs.get("process_drawing_plan") or {})

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

    def _latest_outputs(self, run: AgentRun) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for observation in run.observations:
            if not observation.ok:
                continue
            output = observation.output or {}
            if "parse_result" in output:
                values["parse_result"] = output["parse_result"]
            if "process_plan" in output:
                values["process_plan"] = output["process_plan"]
            if "flow" in output:
                values["flow"] = output["flow"]
            if "annotation_result" in output:
                values["annotation_result"] = output["annotation_result"]
            if "validation_issues" in output:
                values["validation_issues"] = output["validation_issues"]
            if "process_guidance" in output:
                values["process_guidance"] = output["process_guidance"]
            if "final_guidance" in output:
                values["final_guidance"] = output["final_guidance"]
            if "process_drawing_plan" in output:
                values["process_drawing_plan"] = output["process_drawing_plan"]
            if "case" in output:
                values["case"] = output["case"]
            if "cases" in output:
                values["cases"] = output["cases"]
            if "explanations" in output:
                values["explanations"] = output["explanations"]
            if "csv_path" in output:
                values["csv_path"] = output["csv_path"]
        return values


action_module = ActionModule()
