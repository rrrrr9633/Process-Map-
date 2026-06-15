from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


BACKEND_DIR = Path(__file__).resolve().parents[2]
UPLOADS_DIR = BACKEND_DIR / "uploads"


class AgentPerception(BaseModel):
    goal: str
    input_files: list[str] = Field(default_factory=list)
    user_message: str = ""
    intent: str = "general_chat"
    requested_output: str = "chat"
    file_summaries: list[dict[str, Any]] = Field(default_factory=list)
    recommended_tools: list[str] = Field(default_factory=list)
    initial_context: dict[str, Any] = Field(default_factory=dict)
    normalized_inputs: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class PerceptionModule:
    def perceive(
        self,
        *,
        goal: str,
        input_files: list[str] | None = None,
        user_message: str = "",
        initial_context: dict[str, Any] | None = None,
    ) -> AgentPerception:
        files = [self._normalize_file_path(item) for item in (input_files or []) if str(item).strip()]
        context = initial_context or {}
        normalized = dict(context)
        if files and "file_path" not in normalized:
            normalized["file_path"] = files[0]
        if files:
            normalized["input_files"] = files
        intent = self._detect_intent(goal=goal, user_message=user_message, files=files)
        requested_output = self._detect_requested_output(goal=goal, user_message=user_message)
        file_summaries = [self._file_summary(item) for item in files]
        recommended_tools = self._recommended_tools(intent=intent, files=files)

        warnings: list[str] = []
        for summary in file_summaries:
            if not summary["exists"]:
                warnings.append(f"输入文件不存在或不可读：{summary['path']}")

        return AgentPerception(
            goal=goal.strip(),
            input_files=files,
            user_message=user_message.strip(),
            intent=intent,
            requested_output=requested_output,
            file_summaries=file_summaries,
            recommended_tools=recommended_tools,
            initial_context=context,
            normalized_inputs=normalized,
            warnings=warnings,
        )

    def _normalize_file_path(self, value: str) -> str:
        raw = str(value).strip()
        path = Path(raw).expanduser()
        if path.is_absolute():
            return str(path)
        upload_candidate = (UPLOADS_DIR / Path(raw).name).resolve()
        if upload_candidate.is_file():
            return str(upload_candidate)
        agent_upload_candidate = (UPLOADS_DIR / "agent" / Path(raw).name).resolve()
        if agent_upload_candidate.is_file():
            return str(agent_upload_candidate)
        return str(path)

    def _detect_intent(self, *, goal: str, user_message: str, files: list[str]) -> str:
        text = f"{goal} {user_message}".lower()
        if any(keyword in text for keyword in ("保存", "归档", "案例", "入库")):
            return "case_management"
        if any(keyword in text for keyword in ("导出", "下载", "csv", "markdown", "工艺图")):
            return "export"
        if any(keyword in text for keyword in ("生成工序", "工序", "流程", "process")):
            return "process_generation"
        if any(keyword in text for keyword in ("解析", "图纸", "标注", "尺寸", "复核", "风险")) or files:
            return "drawing_analysis"
        if any(keyword in text for keyword in ("状态", "配置", "工具", "能力")):
            return "system_status"
        return "general_chat"

    def _detect_requested_output(self, *, goal: str, user_message: str) -> str:
        text = f"{goal} {user_message}".lower()
        if any(keyword in text for keyword in ("json", "结构化")):
            return "json"
        if any(keyword in text for keyword in ("表格", "csv")):
            return "table"
        if any(keyword in text for keyword in ("文件", "导出", "下载")):
            return "file"
        return "chat"

    def _file_summary(self, file_path: str) -> dict[str, Any]:
        path = Path(file_path).expanduser()
        suffix = path.suffix.lower().lstrip(".")
        kind = "unknown"
        if suffix in {"pdf"}:
            kind = "pdf_drawing"
        elif suffix in {"png", "jpg", "jpeg", "webp", "bmp"}:
            kind = "image_drawing"
        elif suffix in {"dwg", "dxf"}:
            kind = "cad_drawing"
        elif suffix in {"stl", "obj", "ply", "step", "stp", "iges", "igs"}:
            kind = "geometry_3d"
        elif suffix in {"txt", "json"}:
            kind = "structured_text"
        return {
            "path": str(path),
            "name": path.name,
            "suffix": suffix,
            "kind": kind,
            "exists": path.is_file(),
            "size": path.stat().st_size if path.is_file() else 0,
        }

    def _recommended_tools(self, *, intent: str, files: list[str]) -> list[str]:
        tools: list[str] = []
        if intent == "drawing_analysis" and files:
            tools.extend(["parse_drawing", "render_drawing_pages", "analyze_3d_geometry"])
        if intent == "process_generation":
            tools.extend(["parse_drawing", "generate_rule_process_plan", "validate_process_plan"])
        if intent == "case_management":
            tools.extend(["search_cases", "load_case_summary"])
        if intent == "export":
            tools.extend(["render_process_plan_markdown", "export_annotations"])
        if intent == "system_status":
            tools.append("get_case_storage_status")
        return list(dict.fromkeys(tools))


perception_module = PerceptionModule()
