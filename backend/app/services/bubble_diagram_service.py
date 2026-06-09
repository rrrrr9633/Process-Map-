from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.models.annotation import DrawingAnnotation
from app.models.drawing_explanation import BubbleDiagramAsset, DrawingExplanation, DrawingPageExplanation


class BubbleDiagramService:
    def generate(self, explanation: DrawingExplanation, target_dir: str | Path) -> DrawingExplanation:
        if explanation.page_explanations:
            for page_explanation in explanation.page_explanations:
                self.generate_page_explanation(page_explanation, explanation, target_dir)
            if explanation.page_explanations:
                first = explanation.page_explanations[0]
                explanation.page_asset = first.page_asset
                explanation.bubble_asset = first.bubble_asset
                explanation.annotation_result.bubble_diagram_available = any(
                    item.bubble_asset and item.bubble_asset.status == "generated"
                    for item in explanation.page_explanations
                )
            return explanation

        if not explanation.page_asset:
            explanation.bubble_asset = BubbleDiagramAsset(
                file_index=explanation.file_index,
                file_name=explanation.file_name,
                status="failed",
                message="缺少页面预览图，无法生成气泡图",
            )
            return explanation

        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        output_path = target / f"file_{explanation.file_index:03d}_bubble.png"
        try:
            base = Image.open(explanation.page_asset.image_path).convert("RGB")
            canvas = self._build_canvas(base, explanation.annotation_result.annotations)
            canvas.save(output_path)
            explanation.annotation_result.bubble_diagram_available = True
            explanation.bubble_asset = BubbleDiagramAsset(
                file_index=explanation.file_index,
                file_name=explanation.file_name,
                page=explanation.page_asset.page,
                image_path=str(output_path),
                image_url=f"bubbles/{output_path.name}",
                status="generated",
                message="气泡图已生成",
            )
        except Exception as exc:
            explanation.bubble_asset = BubbleDiagramAsset(
                file_index=explanation.file_index,
                file_name=explanation.file_name,
                page=explanation.page_asset.page,
                status="failed",
                message=f"气泡图生成失败：{type(exc).__name__}: {exc}",
            )
        return explanation


    def generate_page_explanation(
        self,
        page_explanation: DrawingPageExplanation,
        explanation: DrawingExplanation,
        target_dir: str | Path,
    ) -> DrawingPageExplanation:
        if not page_explanation.page_asset:
            page_explanation.bubble_asset = BubbleDiagramAsset(
                file_index=explanation.file_index,
                file_name=explanation.file_name,
                page=page_explanation.page,
                status="failed",
                message="缺少页面预览图，无法生成气泡图",
            )
            return page_explanation

        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        output_path = target / f"file_{explanation.file_index:03d}_page_{page_explanation.page}_bubble.png"
        try:
            base = Image.open(page_explanation.page_asset.image_path).convert("RGB")
            canvas = self._build_canvas(base, page_explanation.annotation_result.annotations)
            canvas.save(output_path)
            page_explanation.annotation_result.bubble_diagram_available = True
            page_explanation.bubble_asset = BubbleDiagramAsset(
                file_index=explanation.file_index,
                file_name=explanation.file_name,
                page=page_explanation.page,
                image_path=str(output_path),
                image_url=f"bubbles/{output_path.name}",
                status="generated",
                message="气泡图已生成",
            )
        except Exception as exc:
            page_explanation.bubble_asset = BubbleDiagramAsset(
                file_index=explanation.file_index,
                file_name=explanation.file_name,
                page=page_explanation.page,
                status="failed",
                message=f"气泡图生成失败：{type(exc).__name__}: {exc}",
            )
        return page_explanation

    def _build_canvas(self, base: Image.Image, annotations: list[DrawingAnnotation]) -> Image.Image:
        list_width = 420
        padding = 18
        canvas = Image.new("RGB", (base.width + list_width, max(base.height, 260)), "white")
        canvas.paste(base, (0, 0))
        draw = ImageDraw.Draw(canvas)
        font = ImageFont.load_default()
        strong = ImageFont.load_default()

        draw.line((base.width, 0, base.width, canvas.height), fill=(20, 20, 20), width=2)
        draw.text((base.width + padding, padding), "气泡标注清单", fill=(0, 0, 0), font=strong)

        if not annotations:
            draw.text((base.width + padding, padding + 34), "未识别到可绘制标注", fill=(80, 80, 80), font=font)
            return canvas

        for index, annotation in enumerate(annotations, start=1):
            label = annotation.label or annotation.annotation_id or f"A{index:03d}"
            color = self._color(index)
            if self._has_valid_region(annotation):
                x1, y1, x2, y2 = self._region_to_pixels(annotation, base.width, base.height)
                draw.rectangle((x1, y1, x2, y2), outline=color, width=3)
                bubble_x = max(8, min(base.width - 54, x1))
                bubble_y = max(8, y1 - 32)
                draw.ellipse((bubble_x, bubble_y, bubble_x + 46, bubble_y + 24), fill="white", outline=color, width=3)
                draw.text((bubble_x + 7, bubble_y + 7), label[:6], fill=color, font=font)
                draw.line((bubble_x + 23, bubble_y + 24, x1, y1), fill=color, width=2)

            row_y = padding + 36 + (index - 1) * 56
            if row_y > canvas.height - 40:
                continue
            text = annotation.parameter_name or annotation.normalized_text or annotation.raw_text or label
            value = annotation.parameter_value or ""
            draw.text((base.width + padding, row_y), f"{label}  {text}"[:58], fill=color, font=strong)
            draw.text((base.width + padding, row_y + 18), f"值：{value or '待确认'}  状态：{annotation.review_status}"[:64], fill=(70, 70, 70), font=font)
            draw.text((base.width + padding, row_y + 34), f"原文：{annotation.raw_text or '待确认'}"[:64], fill=(70, 70, 70), font=font)
        return canvas

    def _has_valid_region(self, annotation: DrawingAnnotation) -> bool:
        region = annotation.region
        return region.width > 0 and region.height > 0 and region.x >= 0 and region.y >= 0

    def _region_to_pixels(self, annotation: DrawingAnnotation, width: int, height: int) -> tuple[int, int, int, int]:
        region = annotation.region
        if region.unit == "ratio":
            x1 = int(region.x * width)
            y1 = int(region.y * height)
            x2 = int((region.x + region.width) * width)
            y2 = int((region.y + region.height) * height)
        else:
            x1 = int(region.x)
            y1 = int(region.y)
            x2 = int(region.x + region.width)
            y2 = int(region.y + region.height)
        x1 = max(0, min(width - 1, x1))
        y1 = max(0, min(height - 1, y1))
        x2 = max(x1 + 1, min(width, x2))
        y2 = max(y1 + 1, min(height, y2))
        return x1, y1, x2, y2

    def _color(self, index: int) -> tuple[int, int, int]:
        palette = [
            (220, 20, 60),
            (0, 102, 204),
            (0, 130, 70),
            (180, 90, 0),
            (120, 55, 180),
            (20, 140, 150),
        ]
        return palette[(index - 1) % len(palette)]


bubble_diagram_service = BubbleDiagramService()