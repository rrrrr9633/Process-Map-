from __future__ import annotations

from typing import Any

from app.models.annotation import AnnotationExportRow, DrawingAnnotation, DrawingAnnotationResult


def _clamp_ratio(value: float) -> float:
    return max(0.0, min(1.0, value))


def normalize_annotation(annotation: DrawingAnnotation, *, page: int, file_index: int, index: int) -> DrawingAnnotation:
    region = annotation.region
    if region.unit == "ratio":
        x = _clamp_ratio(float(region.x))
        y = _clamp_ratio(float(region.y))
        width = _clamp_ratio(float(region.width))
        height = _clamp_ratio(float(region.height))
        if width <= 0 or height <= 0:
            width = 0.0
            height = 0.0
        if x + width > 1.0:
            width = max(0.0, 1.0 - x)
        if y + height > 1.0:
            height = max(0.0, 1.0 - y)
        region.x = x
        region.y = y
        region.width = width
        region.height = height
    region.page = page
    annotation.region = region

    if not annotation.annotation_id or annotation.annotation_id.startswith("A"):
        annotation.annotation_id = f"F{file_index:02d}P{page:02d}A{index:03d}"
    if not annotation.label:
        annotation.label = annotation.annotation_id.split("A")[-1][-3:]
    if region.width <= 0 or region.height <= 0:
        annotation.review_status = "needs_manual_review"
        if not annotation.review_reason:
            annotation.review_reason = "缺少有效标注区域坐标，需人工校正"
    return annotation



def convert_annotation_region_to_ratio(
    annotation: DrawingAnnotation,
    page_width: int,
    page_height: int,
) -> DrawingAnnotation:
    region = annotation.region
    if region.unit != "pixel" or page_width <= 0 or page_height <= 0:
        return annotation
    region.x = float(region.x) / page_width
    region.y = float(region.y) / page_height
    region.width = float(region.width) / page_width
    region.height = float(region.height) / page_height
    region.unit = "ratio"
    annotation.region = region
    return annotation


def normalize_annotation_result(
    value: Any,
    *,
    page: int,
    file_index: int,
) -> DrawingAnnotationResult:
    if not isinstance(value, DrawingAnnotationResult):
        if isinstance(value, dict):
            from pydantic import ValidationError

            annotations_raw = value.get("annotations") if isinstance(value.get("annotations"), list) else []
            export_rows_raw = value.get("export_rows") if isinstance(value.get("export_rows"), list) else []
            annotations: list[DrawingAnnotation] = []
            for index, item in enumerate(annotations_raw, start=1):
                if not isinstance(item, dict):
                    continue
                candidate = dict(item)
                candidate.setdefault("annotation_id", f"F{file_index:02d}P{page:02d}A{index:03d}")
                try:
                    annotations.append(DrawingAnnotation.model_validate(candidate))
                except ValidationError:
                    continue
            export_rows: list[AnnotationExportRow] = []
            for index, item in enumerate(export_rows_raw, start=1):
                if not isinstance(item, dict):
                    continue
                candidate = dict(item)
                candidate.setdefault("row_no", index)
                try:
                    export_rows.append(AnnotationExportRow.model_validate(candidate))
                except ValidationError:
                    continue
            value = DrawingAnnotationResult(annotations=annotations, export_rows=export_rows)
        else:
            return DrawingAnnotationResult()

    normalized_annotations = [
        normalize_annotation(item, page=page, file_index=file_index, index=index)
        for index, item in enumerate(value.annotations, start=1)
    ]
    export_rows = rebuild_export_rows(normalized_annotations) if normalized_annotations else value.export_rows
    review_required_count = sum(
        1 for item in normalized_annotations if item.review_status in {"pending", "needs_manual_review"}
    )
    return DrawingAnnotationResult(
        annotations=normalized_annotations,
        export_rows=export_rows,
        bubble_diagram_available=value.bubble_diagram_available,
        review_required_count=review_required_count,
    )


def rebuild_export_rows(annotations: list[DrawingAnnotation]) -> list[AnnotationExportRow]:
    rows: list[AnnotationExportRow] = []
    for index, annotation in enumerate(annotations, start=1):
        rows.append(
            AnnotationExportRow(
                row_no=index,
                annotation_id=annotation.annotation_id,
                parameter_name=annotation.parameter_name
                or annotation.normalized_text
                or annotation.raw_text
                or annotation.annotation_id,
                parameter_value=annotation.parameter_value or "",
                upper_limit=annotation.upper_limit or "",
                lower_limit=annotation.lower_limit or "",
                unit=annotation.unit or "",
                semantic_type=annotation.semantic_type,
                review_status=annotation.review_status,
                source=annotation.source,
                confidence=annotation.confidence,
            )
        )
    return rows


def merge_annotation_results(results: list[DrawingAnnotationResult]) -> DrawingAnnotationResult:
    annotations: list[DrawingAnnotation] = []
    for result in results:
        annotations.extend(result.annotations)
    export_rows = rebuild_export_rows(annotations)
    review_required_count = sum(
        1 for item in annotations if item.review_status in {"pending", "needs_manual_review"}
    )
    return DrawingAnnotationResult(
        annotations=annotations,
        export_rows=export_rows,
        bubble_diagram_available=any(item.bubble_diagram_available for item in results),
        review_required_count=review_required_count,
    )

def map_view_local_regions_to_page(
    result: DrawingAnnotationResult,
    *,
    view_x: float,
    view_y: float,
    view_width: float,
    view_height: float,
) -> DrawingAnnotationResult:
    """将视图局部 ratio 坐标映射回整页 ratio 坐标。"""
    if view_width <= 0 or view_height <= 0:
        return result
    for annotation in result.annotations:
        region = annotation.region
        if region.unit != "ratio":
            continue
        local_x = float(region.x)
        local_y = float(region.y)
        local_w = float(region.width)
        local_h = float(region.height)
        region.x = _clamp_ratio(view_x + local_x * view_width)
        region.y = _clamp_ratio(view_y + local_y * view_height)
        region.width = _clamp_ratio(local_w * view_width)
        region.height = _clamp_ratio(local_h * view_height)
        annotation.region = region
    return result
