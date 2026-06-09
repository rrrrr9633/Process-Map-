from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image


@dataclass(frozen=True)
class SheetViewRegion:
    view_index: int
    label: str
    x: float
    y: float
    width: float
    height: float

    def as_dict(self) -> dict[str, float | int | str]:
        return {
            "view_index": self.view_index,
            "label": self.label,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }


def _ink_density(ink: list[list[bool]], x0: int, y0: int, x1: int, y1: int) -> float:
    if x1 <= x0 or y1 <= y0:
        return 0.0
    total = 0
    hits = 0
    for y in range(y0, y1):
        row = ink[y]
        for x in range(x0, x1):
            total += 1
            if row[x]:
                hits += 1
    return hits / total if total else 0.0


def _build_ink_grid(image: Image.Image, max_side: int = 960) -> tuple[list[list[bool]], int, int]:
    gray = image.convert("L")
    width, height = gray.size
    scale = min(1.0, max_side / max(width, height))
    if scale < 1.0:
        gray = gray.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.Resampling.BILINEAR)
    pixels = list(gray.getdata())
    w, h = gray.size
    ink: list[list[bool]] = []
    for y in range(h):
        row_start = y * w
        ink.append([pixels[row_start + x] < 210 for x in range(w)])
    return ink, w, h


def split_sheet_views(image_path: Path, *, max_views: int = 4) -> list[SheetViewRegion]:
    """按墨迹分布将单页图纸切成多个视图区域（相对整页 0~1 比例坐标）。"""
    path = Path(image_path)
    if not path.is_file():
        return [SheetViewRegion(1, "整页", 0.0, 0.0, 1.0, 1.0)]

    try:
        with Image.open(path) as image:
            ink, w, h = _build_ink_grid(image)
    except Exception:
        return [SheetViewRegion(1, "整页", 0.0, 0.0, 1.0, 1.0)]

    if w < 8 or h < 8:
        return [SheetViewRegion(1, "整页", 0.0, 0.0, 1.0, 1.0)]

    mx, my = w // 2, h // 2
    quadrants = (
        _ink_density(ink, 0, 0, mx, my),
        _ink_density(ink, mx, 0, w, my),
        _ink_density(ink, 0, my, mx, h),
        _ink_density(ink, mx, my, w, h),
    )
    active_quads = sum(1 for value in quadrants if value >= 0.018)

    regions: list[SheetViewRegion] = []
    if max_views >= 4 and active_quads >= 3:
        boxes = (
            (0.0, 0.0, 0.5, 0.5, "视图-左上"),
            (0.5, 0.0, 0.5, 0.5, "视图-右上"),
            (0.0, 0.5, 0.5, 0.5, "视图-左下"),
            (0.5, 0.5, 0.5, 0.5, "视图-右下"),
        )
        for index, (x, y, width, height, label) in enumerate(boxes, start=1):
            if quadrants[index - 1] >= 0.012:
                regions.append(SheetViewRegion(index, label, x, y, width, height))
        if len(regions) >= 2:
            return regions[:max_views]

    left = _ink_density(ink, 0, 0, mx, w)
    right = _ink_density(ink, mx, 0, w, h)
    top = _ink_density(ink, 0, 0, w, my)
    bottom = _ink_density(ink, 0, my, w, h)

    if max_views >= 2 and left >= 0.02 and right >= 0.02 and abs(left - right) < 0.25:
        return [
            SheetViewRegion(1, "视图-左", 0.0, 0.0, 0.5, 1.0),
            SheetViewRegion(2, "视图-右", 0.5, 0.0, 0.5, 1.0),
        ]
    if max_views >= 2 and top >= 0.02 and bottom >= 0.02 and abs(top - bottom) < 0.25:
        return [
            SheetViewRegion(1, "视图-上", 0.0, 0.0, 1.0, 0.5),
            SheetViewRegion(2, "视图-下", 0.0, 0.5, 1.0, 0.5),
        ]

    return [SheetViewRegion(1, "整页", 0.0, 0.0, 1.0, 1.0)]


def crop_view_payload(
    image_path: Path,
    region: SheetViewRegion,
    *,
    page: int,
) -> dict[str, str]:
    with Image.open(image_path) as image:
        width, height = image.size
        left = int(region.x * width)
        top = int(region.y * height)
        right = int(min(width, (region.x + region.width) * width))
        bottom = int(min(height, (region.y + region.height) * height))
        if right - left < 4 or bottom - top < 4:
            cropped = image.convert("RGB")
        else:
            cropped = image.crop((left, top, right, bottom)).convert("RGB")
        import base64
        import io

        buffer = io.BytesIO()
        cropped.save(buffer, format="PNG")
        data = buffer.getvalue()
        return {
            "name": f"page_{page}_view_{region.view_index}.png",
            "page": str(page),
            "view_index": str(region.view_index),
            "mime_type": "image/png",
            "base64": base64.b64encode(data).decode("ascii"),
            "source": "sheet_view_crop",
        }