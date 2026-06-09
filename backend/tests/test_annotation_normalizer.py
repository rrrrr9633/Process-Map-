from app.models.annotation import DrawingAnnotation, DrawingAnnotationResult
from app.services.annotation_normalizer import (
    convert_annotation_region_to_ratio,
    merge_annotation_results,
    normalize_annotation,
    rebuild_export_rows,
)


def test_normalize_annotation_clamps_ratio_region():
    annotation = DrawingAnnotation(
        annotation_id="A001",
        raw_text="φ50",
        region={"page": 1, "x": 1.2, "y": -0.1, "width": 0.5, "height": 0.4, "unit": "ratio"},
    )
    normalized = normalize_annotation(annotation, page=2, file_index=3, index=1)
    assert normalized.region.page == 2
    assert normalized.region.x == 1.0
    assert normalized.region.y == 0.0
    assert normalized.region.width <= 0.5


def test_merge_annotation_results_keeps_all_pages():
    first = DrawingAnnotationResult(
        annotations=[DrawingAnnotation(annotation_id="F01P01A001", raw_text="a")],
        export_rows=[],
    )
    second = DrawingAnnotationResult(
        annotations=[DrawingAnnotation(annotation_id="F01P02A001", raw_text="b")],
        export_rows=[],
    )
    merged = merge_annotation_results([first, second])
    assert len(merged.annotations) == 2

def test_rebuild_export_rows_from_annotations():
    annotation = DrawingAnnotation(annotation_id="F01P01A001", raw_text="φ50", parameter_value="50")
    rows = rebuild_export_rows([annotation])
    assert len(rows) == 1
    assert rows[0].parameter_name == "φ50"


def test_convert_annotation_region_to_ratio():
    annotation = DrawingAnnotation(
        annotation_id="F01P01A001",
        raw_text="φ50",
        region={"page": 1, "x": 100, "y": 50, "width": 200, "height": 100, "unit": "pixel"},
    )
    converted = convert_annotation_region_to_ratio(annotation, page_width=1000, page_height=500)
    assert converted.region.unit == "ratio"
    assert abs(converted.region.x - 0.1) < 1e-6
    assert abs(converted.region.y - 0.1) < 1e-6
