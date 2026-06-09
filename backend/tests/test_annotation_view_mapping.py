from app.models.annotation import BoundingBox, DrawingAnnotation, DrawingAnnotationResult
from app.services.annotation_normalizer import map_view_local_regions_to_page


def test_map_view_local_regions_to_page() -> None:
    annotation = DrawingAnnotation(
        annotation_id="A001",
        raw_text="φ50",
        region=BoundingBox(x=0.1, y=0.2, width=0.3, height=0.4, unit="ratio"),
    )
    result = DrawingAnnotationResult(annotations=[annotation], export_rows=[])
    mapped = map_view_local_regions_to_page(
        result,
        view_x=0.5,
        view_y=0.0,
        view_width=0.5,
        view_height=1.0,
    )
    region = mapped.annotations[0].region
    assert abs(region.x - 0.55) < 1e-6
    assert abs(region.y - 0.2) < 1e-6
    assert abs(region.width - 0.15) < 1e-6