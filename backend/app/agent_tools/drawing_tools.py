from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agent_tools.contracts import (
    AgentToolCategory,
    AgentToolDefinition,
    AgentToolPermission,
    AgentToolSpec,
)
from app.services.cad_render_service import cad_render_service
from app.services.drawing_explanation_service import drawing_explanation_service
from app.services.drawing_parser import DrawingParser
from app.services.geometry3d_service import geometry3d_service


_parser = DrawingParser()


def drawing_agent_tools() -> list[AgentToolDefinition]:
    return [
        AgentToolDefinition(
            spec=AgentToolSpec(
                name="parse_drawing",
                description="解析 PDF、图片、DXF、DWG 或 3D 文件，返回结构化图纸信息和风险。",
                category=AgentToolCategory.DRAWING,
                permission=AgentToolPermission.READ_ONLY,
                input_schema={"file_path": "absolute path string"},
                output_schema={"parse_result": "DrawingParseResult JSON", "risk_count": "int"},
                model_callable=True,
                cacheable=True,
                max_runtime_seconds=20,
            ),
            handler=parse_drawing_tool,
        ),
        AgentToolDefinition(
            spec=AgentToolSpec(
                name="render_drawing_pages",
                description="把图纸渲染为可供多模态模型观察的页面图片资产。",
                category=AgentToolCategory.DRAWING,
                permission=AgentToolPermission.READ_ONLY,
                input_schema={
                    "file_path": "absolute path string",
                    "target_dir": "absolute path string",
                    "file_index": "int, default 1",
                },
                output_schema={"pages": "list of page assets"},
                model_callable=True,
                cacheable=True,
                max_runtime_seconds=60,
            ),
            handler=render_drawing_pages_tool,
        ),
        AgentToolDefinition(
            spec=AgentToolSpec(
                name="analyze_3d_geometry",
                description="分析 STL/OBJ/PLY/STEP/IGES 等三维模型，返回几何摘要和限制。",
                category=AgentToolCategory.DRAWING,
                permission=AgentToolPermission.READ_ONLY,
                input_schema={"file_path": "absolute path string"},
                output_schema={"geometry": "summary JSON", "prompt_text": "string"},
                model_callable=True,
                cacheable=True,
                max_runtime_seconds=30,
            ),
            handler=analyze_3d_geometry_tool,
        ),
        AgentToolDefinition(
            spec=AgentToolSpec(
                name="render_cad_preview",
                description="渲染 DXF/DWG 预览图，依赖本机 CAD 渲染能力。",
                category=AgentToolCategory.DRAWING,
                permission=AgentToolPermission.READ_ONLY,
                input_schema={
                    "file_path": "absolute path string",
                    "target_dir": "absolute path string",
                    "file_index": "int, default 1",
                },
                output_schema={"pages": "list of CAD preview page assets"},
                model_callable=True,
                cacheable=True,
                max_runtime_seconds=60,
            ),
            handler=render_cad_preview_tool,
        ),
    ]


def parse_drawing_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    path = _existing_path(arguments.get("file_path"))
    parse_result = _parser.parse_file(path)
    return {
        "parse_result": parse_result.model_dump(mode="json"),
        "risk_count": len(parse_result.risk_flags),
        "requires_human_review": bool(parse_result.risk_flags),
    }


def render_drawing_pages_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    path = _existing_path(arguments.get("file_path"))
    target_dir = _target_dir(arguments.get("target_dir"))
    file_index = int(arguments.get("file_index") or 1)
    pages = drawing_explanation_service.render_all_pages(path, target_dir, file_index, path.name)
    return {
        "pages": [
            {
                "page": page,
                "asset": asset.model_dump(mode="json"),
                "payload_meta": {
                    "name": payload.get("name", ""),
                    "mime_type": payload.get("mime_type", ""),
                    "source": payload.get("source", ""),
                    "has_base64": bool(payload.get("base64")),
                },
                "ocr_text_preview": ocr_text[:500],
            }
            for page, asset, payload, ocr_text in pages
        ],
        "requires_human_review": not bool(pages),
    }


def analyze_3d_geometry_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    path = _existing_path(arguments.get("file_path"))
    analysis = geometry3d_service.analyze_file(path)
    return {
        "geometry": {
            "file_name": analysis.file_name,
            "suffix": analysis.suffix,
            "status": analysis.status,
            "summary": analysis.summary,
            "dimensions": analysis.dimensions,
            "bbox_min": analysis.bbox_min,
            "bbox_max": analysis.bbox_max,
            "dominant_axis": analysis.dominant_axis,
            "risk_notes": analysis.risk_notes or [],
        },
        "prompt_text": geometry3d_service.to_prompt_text(analysis),
        "requires_human_review": analysis.status != "ok" or bool(analysis.risk_notes),
    }


def render_cad_preview_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    path = _existing_path(arguments.get("file_path"))
    target_dir = _target_dir(arguments.get("target_dir"))
    file_index = int(arguments.get("file_index") or 1)
    pages = cad_render_service.render_pages(path, target_dir, file_index, path.name, max_pages=int(arguments.get("max_pages") or 1))
    return {
        "pages": [
            {
                "asset": asset.model_dump(mode="json"),
                "payload_meta": {
                    "name": payload.get("name", ""),
                    "mime_type": payload.get("mime_type", ""),
                    "source": payload.get("source", ""),
                    "has_base64": bool(payload.get("base64")),
                },
            }
            for asset, payload in pages
        ],
        "requires_human_review": not bool(pages),
    }


def _existing_path(value: Any) -> Path:
    if not value:
        raise ValueError("缺少 file_path")
    path = Path(str(value)).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path


def _target_dir(value: Any) -> Path:
    if not value:
        raise ValueError("缺少 target_dir")
    path = Path(str(value)).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path