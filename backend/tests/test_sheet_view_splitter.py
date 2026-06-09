from pathlib import Path

from PIL import Image

from app.services.sheet_view_splitter import crop_view_payload, split_sheet_views


def test_split_sheet_views_quadrant_layout(tmp_path: Path) -> None:
    image_path = tmp_path / "quad.png"
    canvas = Image.new("RGB", (800, 600), "white")
    for box in [(20, 20, 360, 260), (420, 20, 760, 260), (20, 320, 360, 560), (420, 320, 760, 560)]:
        region = Image.new("RGB", (box[2] - box[0], box[3] - box[1]), "black")
        canvas.paste(region, (box[0], box[1]))
    canvas.save(image_path)

    regions = split_sheet_views(image_path, max_views=4)
    assert len(regions) >= 2
    payload = crop_view_payload(image_path, regions[0], page=1)
    assert payload["mime_type"] == "image/png"
    assert payload["base64"]


def test_split_missing_file_defaults_full_page() -> None:
    regions = split_sheet_views(Path("/tmp/not-a-real-drawing.png"))
    assert len(regions) == 1
    assert regions[0].width == 1.0