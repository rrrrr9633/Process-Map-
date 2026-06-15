from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agent_runtime.state import AgentRun
from app.agent_runtime.skills import agent_skillset
from app.agent_tools.contracts import AgentToolObservation


class AgentMemorySnapshot(BaseModel):
    short_term: dict[str, Any] = Field(default_factory=dict)
    long_term_refs: list[dict[str, Any]] = Field(default_factory=list)


class MemoryModule:
    def build_snapshot(
        self,
        *,
        run: AgentRun,
        perception: dict[str, Any],
        observations: list[AgentToolObservation] | None = None,
    ) -> AgentMemorySnapshot:
        recent_observations = [
            observation.model_dump(mode="json")
            for observation in (observations or run.observations)[-8:]
        ]
        short_term = {
            "goal": run.goal,
            "current_step": run.current_step,
            "plan": run.plan[-6:],
            "input_files": run.input_files,
            "perception": perception,
            "conversation": perception.get("initial_context", {}).get("recent_messages", [])[-12:]
            if isinstance(perception.get("initial_context"), dict)
            else [],
            "last_run": perception.get("initial_context", {}).get("last_run", {})
            if isinstance(perception.get("initial_context"), dict)
            else {},
            "recent_observations": recent_observations,
            "risks": run.risks[-8:],
            "questions": run.questions[-8:],
        }
        long_term_refs = [
            {
                "source": "case_tools",
                "hint": "需要历史经验时优先调用 search_cases 或 load_case_summary。",
            },
            {
                "source": "knowledge_base",
                "hint": "业务长期记忆当前由案例库和 knowledge_base 目录承载。",
            },
            *agent_skillset.case_memory_hints(perception=perception),
        ]
        short_term["skill_hints"] = agent_skillset.planner_rules(
            perception=perception,
            available_tool_names={
                "parse_drawing",
                "render_drawing_pages",
                "analyze_3d_geometry",
                "render_cad_preview",
                "search_cases",
                "load_case_summary",
                "generate_rule_process_plan",
                "validate_process_plan",
                "build_process_guidance",
                "build_final_guidance",
                "build_process_drawing_plan",
                "render_process_drawing_assets",
                "render_process_plan_markdown",
                "archive_process_plan_markdown",
                "export_annotations",
                "save_case",
                "update_case_status",
                "add_case_human_edit",
                "mark_case_ai_error",
                "get_case_storage_status",
            },
        )
        return AgentMemorySnapshot(short_term=short_term, long_term_refs=long_term_refs)


memory_module = MemoryModule()
