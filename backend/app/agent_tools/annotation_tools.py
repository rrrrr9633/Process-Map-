from __future__ import annotations

from typing import Any

from app.agent_tools.contracts import (
    AgentToolCategory,
    AgentToolDefinition,
    AgentToolPermission,
    AgentToolSpec,
)
from app.models.annotation import DrawingAnnotationResult
from app.services.annotation_normalizer import (
    map_view_local_regions_to_page,
    merge_annotation_results,
    normalize_annotation_result,
    rebuild_export_rows,
)


def annotation_agent_tools() -> list[AgentToolDefinition]:
    return [
        AgentToolDefinition(
            spec=AgentToolSpec(
                name="normalize_annotations",
                description="归一化图纸标注坐标、编号和导出行，适合接收模型或人工标注草稿后清洗。",
                category=AgentToolCategory.DRAWING,
                permission=AgentToolPermission.GENERATE,
                input_schema={
                    "annotation_result": "DrawingAnnotationResult JSON",
                    "page": "int, default 1",
                    "file_index": "int, default 1",
                },
                output_schema={"annotation_result": "normalized DrawingAnnotationResult JSON"},
                model_callable=False,
                cacheable=False,
                max_runtime_seconds=10,
            ),
            handler=normalize_annotations_tool,
        ),
        AgentToolDefinition(
            spec=AgentToolSpec(
                name="merge_annotation_results",
                description="合并多页或多文件标注结果，并重建统一导出行。",
                category=AgentToolCategory.DRAWING,
                permission=AgentToolPermission.GENERATE,
                input_schema={"annotation_results": "list of DrawingAnnotationResult JSON"},
                output_schema={"annotation_result": "merged DrawingAnnotationResult JSON"},
                model_callable=False,
                cacheable=False,
                max_runtime_seconds=10,
            ),
            handler=merge_annotation_results_tool,
        ),
        AgentToolDefinition(
            spec=AgentToolSpec(
                name="map_view_annotations_to_page",
                description="把局部视图 ratio 标注坐标映射回整页 ratio 坐标。",
                category=AgentToolCategory.DRAWING,
                permission=AgentToolPermission.GENERATE,
                input_schema={
                    "annotation_result": "DrawingAnnotationResult JSON",
                    "view_x": "float ratio",
                    "view_y": "float ratio",
                    "view_width": "float ratio",
                    "view_height": "float ratio",
                },
                output_schema={"annotation_result": "page-space DrawingAnnotationResult JSON"},
                model_callable=False,
                cacheable=False,
                max_runtime_seconds=10,
            ),
            handler=map_view_annotations_to_page_tool,
        ),
        AgentToolDefinition(
            spec=AgentToolSpec(
                name="rebuild_annotation_export_rows",
                description="根据标注列表重建 CSV/JSON 导出行，不改变标注坐标。",
                category=AgentToolCategory.EXPORT,
                permission=AgentToolPermission.GENERATE,
                input_schema={"annotation_result": "DrawingAnnotationResult JSON"},
                output_schema={"export_rows": "list of AnnotationExportRow JSON"},
                model_callable=False,
                cacheable=False,
                max_runtime_seconds=10,
            ),
            handler=rebuild_annotation_export_rows_tool,
        ),
    ]


def normalize_annotations_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    result = normalize_annotation_result(
        arguments.get("annotation_result") or {},
        page=int(arguments.get("page") or 1),
        file_index=int(arguments.get("file_index") or 1),
    )
    return {
        "annotation_result": result.model_dump(mode="json"),
        "requires_human_review": result.review_required_count > 0,
    }


def merge_annotation_results_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    values = arguments.get("annotation_results") or []
    if not isinstance(values, list):
        raise ValueError("annotation_results 必须是列表")
    results = [DrawingAnnotationResult.model_validate(item or {}) for item in values]
    merged = merge_annotation_results(results)
    return {
        "annotation_result": merged.model_dump(mode="json"),
        "requires_human_review": merged.review_required_count > 0,
    }


def map_view_annotations_to_page_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    result = DrawingAnnotationResult.model_validate(arguments.get("annotation_result") or {})
    mapped = map_view_local_regions_to_page(
        result,
        view_x=float(arguments.get("view_x") or 0),
        view_y=float(arguments.get("view_y") or 0),
        view_width=float(arguments.get("view_width") or 0),
        view_height=float(arguments.get("view_height") or 0),
    )
    return {
        "annotation_result": mapped.model_dump(mode="json"),
        "requires_human_review": mapped.review_required_count > 0,
    }


def rebuild_annotation_export_rows_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    result = DrawingAnnotationResult.model_validate(arguments.get("annotation_result") or {})
    rows = rebuild_export_rows(result.annotations)
    return {"export_rows": [row.model_dump(mode="json") for row in rows]}
