from __future__ import annotations

from pathlib import Path
from typing import Any


class AgentSkillset:
    def routing_hints(self, *, perception: dict[str, Any], available_tool_names: set[str]) -> list[dict[str, Any]]:
        intent = str(perception.get("intent") or "general_chat")
        requested_output = str(perception.get("requested_output") or "chat")
        files = perception.get("input_files") if isinstance(perception.get("input_files"), list) else []
        latest = perception.get("initial_context", {}).get("last_run", {}) if isinstance(perception.get("initial_context"), dict) else {}

        routes: list[dict[str, Any]] = []
        self._add_route(routes, available_tool_names, "get_case_storage_status", intent == "system_status", "用户询问系统、工具、案例库或存储状态。")
        self._add_route(routes, available_tool_names, "parse_drawing", bool(files), "有新图纸或模型文件时先解析输入，建立后续工具的结构化基础。")
        self._add_route(routes, available_tool_names, "render_drawing_pages", bool(files) and intent in {"drawing_analysis", "process_generation"}, "PDF/图片/CAD 图纸需要视觉页资产时再渲染。")
        self._add_route(routes, available_tool_names, "analyze_3d_geometry", any(_is_3d_file(item) for item in files), "STL/STEP/IGES/OBJ 等三维模型需要先分析包围盒、主轴和几何风险。")
        self._add_route(routes, available_tool_names, "search_cases", intent in {"process_generation", "case_management"} or _has_process_outputs(latest), "生成或复核工艺时先找相似历史案例，避免重复犯错。")
        self._add_route(routes, available_tool_names, "generate_rule_process_plan", intent == "process_generation", "已有图纸解析后生成确定性工序方案。")
        self._add_route(routes, available_tool_names, "validate_process_plan", intent == "process_generation", "生成工序后必须校验覆盖性、风险和人工复核项。")
        self._add_route(routes, available_tool_names, "build_process_guidance", intent == "process_generation", "工序和解析结果可用后生成面向工艺人员的指导。")
        self._add_route(routes, available_tool_names, "build_final_guidance", intent == "process_generation", "案例、标注和工序信息齐全后汇总最终指导。")
        self._add_route(routes, available_tool_names, "build_process_drawing_plan", "工艺图" in str(perception.get("goal") or ""), "用户要求工艺图时先生成工艺图计划。")
        self._add_route(routes, available_tool_names, "render_process_plan_markdown", requested_output in {"table", "file"} or intent == "export", "用户要求导出/下载/Markdown 时先渲染文本预览。")
        self._add_route(routes, available_tool_names, "archive_process_plan_markdown", intent == "export" and requested_output == "file", "真正落盘导出需要人工确认。")
        self._add_route(routes, available_tool_names, "save_case", intent == "case_management", "保存案例属于写入动作，需要人工确认。")
        return routes

    def process_planning_rules(self) -> list[str]:
        return [
            "工艺规划优先顺序：读图纸证据 -> 找相似案例 -> 生成规则工序 -> 校验 -> 生成工艺指导 -> 必要时导出。",
            "曲轴/轴类零件通常关注毛坯、中心孔/基准、粗车、半精、热处理/表面强化、精磨、动平衡、清洗防锈、终检。",
            "不要凭空补材料、热处理、精度等级；图纸没有证据时标记为待复核。",
            "如果图纸解析失败或文件缺失，不要继续生成确定性工序，先要求补充文件或换用固定分析。",
            "生成工序后必须尽量调用 validate_process_plan，除非用户明确只要简短建议。",
        ]

    def quality_rules(self) -> list[str]:
        return [
            "质检必须覆盖关键尺寸、形位公差、粗糙度、硬度/热处理、探伤、动平衡、清洁度和追溯项中已出现或业务强相关的项目。",
            "任何低置信度标注、agent_reasoning 来源、缺少图纸证据的推断，都必须进入人工复核。",
            "校验输出要转成人能执行的复核点，不要只说 validation failed。",
            "发现工具输出冲突时，优先保留图纸解析证据，并要求人工确认。",
        ]

    def case_memory_hints(self, *, perception: dict[str, Any]) -> list[dict[str, Any]]:
        intent = str(perception.get("intent") or "")
        hints = [
            {
                "source": "case_memory",
                "rule": "有工序生成、复核、保存案例需求时，优先检索历史案例并加载最相近案例摘要。",
                "tools": ["search_cases", "load_case_summary"],
            },
            {
                "source": "case_quality_feedback",
                "rule": "如果历史案例存在 ai_error_count 或 human_edit_count，需要把这些当成反思依据，避免重复错误。",
                "tools": ["load_case_summary", "mark_case_ai_error", "add_case_human_edit"],
            },
        ]
        if intent == "case_management":
            hints.append(
                {
                    "source": "case_write_policy",
                    "rule": "保存、改状态、记录人工修改、记录 AI 错误都属于写入动作，必须有明确用户意图或人工确认。",
                    "tools": ["save_case", "update_case_status", "add_case_human_edit", "mark_case_ai_error"],
                }
            )
        return hints

    def planner_rules(self, *, perception: dict[str, Any], available_tool_names: set[str]) -> list[str]:
        routes = self.routing_hints(perception=perception, available_tool_names=available_tool_names)
        route_text = [
            f"当条件成立：{item['when']}，优先考虑 {item['tool_name']}；原因：{item['reason']}"
            for item in routes
        ]
        return [
            *route_text,
            *self.process_planning_rules(),
            *self.quality_rules(),
            "写入、导出落盘、保存、改状态类工具即使在工具清单中，也只能在用户明确要求或人工确认链路中使用。",
        ]

    def _add_route(
        self,
        routes: list[dict[str, Any]],
        available_tool_names: set[str],
        tool_name: str,
        condition: bool,
        reason: str,
    ) -> None:
        if condition and tool_name in available_tool_names:
            routes.append({"tool_name": tool_name, "when": "当前输入/意图匹配", "reason": reason})


def _is_3d_file(file_path: Any) -> bool:
    return Path(str(file_path)).suffix.lower().lstrip(".") in {"stl", "obj", "ply", "step", "stp", "iges", "igs"}


def _has_process_outputs(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if "process_plan" in value:
        return True
    run = value.get("run")
    return isinstance(run, dict) and bool(run.get("final_result") or run.get("observations"))


agent_skillset = AgentSkillset()
