from __future__ import annotations

from pathlib import Path
import textwrap

from PIL import Image, ImageDraw, ImageFont

from app.models.annotation import DrawingAnnotation
from app.models.drawing_explanation import BubbleDiagramAsset, DrawingExplanation, DrawingPageExplanation
from app.services.engineering_text import normalize_engineering_text


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
            font_message = f"；字体：{canvas.info.get('bubble_font', 'unknown')}"
            canvas.save(output_path)
            explanation.annotation_result.bubble_diagram_available = True
            explanation.bubble_asset = BubbleDiagramAsset(
                file_index=explanation.file_index,
                file_name=explanation.file_name,
                page=explanation.page_asset.page,
                image_path=str(output_path),
                image_url=f"bubbles/{output_path.name}",
                status="generated",
                message=f"气泡图已生成{font_message}",
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
            font_message = f"；字体：{canvas.info.get('bubble_font', 'unknown')}"
            canvas.save(output_path)
            page_explanation.annotation_result.bubble_diagram_available = True
            page_explanation.bubble_asset = BubbleDiagramAsset(
                file_index=explanation.file_index,
                file_name=explanation.file_name,
                page=page_explanation.page,
                image_path=str(output_path),
                image_url=f"bubbles/{output_path.name}",
                status="generated",
                message=f"气泡图已生成{font_message}",
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
        list_width = 560
        padding = 20
        row_height = 86
        canvas_height = max(base.height, padding * 2 + 40 + max(1, len(annotations)) * row_height)
        canvas = Image.new("RGB", (base.width + list_width, canvas_height), "white")
        canvas.paste(base, (0, 0))
        draw = ImageDraw.Draw(canvas)
        font = self._load_font(18)
        small = self._load_font(15)
        strong = self._load_font(20)
        canvas.info["bubble_font"] = self._font_name(font)

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
            row_y = padding + 40 + (index - 1) * row_height
            if row_y > canvas.height - 40:
                continue
            text = self._safe_text(annotation.parameter_name or annotation.normalized_text or annotation.raw_text or label)
            value = self._safe_text(annotation.parameter_value or annotation.normalized_text or annotation.raw_text or "待确认")
            status = self._status_label(annotation.review_status)
            summary = self._annotation_summary(annotation)
            draw.text((base.width + padding, row_y), f"{label}  {text}", fill=color, font=strong)
            draw.text((base.width + padding, row_y + 25), f"值：{value}  状态：{status}", fill=(55, 55, 55), font=font)
            for line_index, line in enumerate(self._wrap_text(summary, 38)[:2]):
                draw.text((base.width + padding, row_y + 49 + line_index * 18), line, fill=(80, 80, 80), font=small)
        return canvas

    def _load_font(self, size: int):
        candidates = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/System/Library/Fonts/STHeiti Medium.ttc",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.otf",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.otf",
            "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/truetype/arphic/uming.ttc",
            "/usr/share/fonts/truetype/arphic/ukai.ttc",
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simfang.ttf",
            "C:/Windows/Fonts/simsun.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        for candidate in candidates:
            path = Path(candidate)
            if path.is_file():
                try:
                    return ImageFont.truetype(str(path), size=size)
                except Exception:
                    continue
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()

    def _font_name(self, font) -> str:
        path = getattr(font, "path", "")
        if path:
            return str(path)
        try:
            return font.getname()[0]
        except Exception:
            return "PIL default"

    def _safe_text(self, value: str) -> str:
        return normalize_engineering_text(value)

    def _wrap_text(self, value: str, width: int) -> list[str]:
        text = self._safe_text(value)
        if not text:
            return []
        return textwrap.wrap(text, width=width, break_long_words=False, replace_whitespace=False) or [text]

    def _status_label(self, status: str) -> str:
        return {
            "accepted": "可用",
            "pending": "待复核",
            "needs_manual_review": "需人工确认",
            "rejected": "已拒绝",
        }.get(status, status or "待复核")

    def _annotation_summary(self, annotation: DrawingAnnotation) -> str:
        name = annotation.parameter_name or annotation.label or annotation.annotation_id
        value = annotation.parameter_value or annotation.normalized_text or annotation.raw_text or "待确认"
        source = "图像识别" if annotation.source == "pdf_page_image" else "PDF文本" if annotation.source == "pdf_text" else "模型推理"
        return f"说明：{name} = {value}；来源：{source}；置信度：{annotation.confidence:.2f}"

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
