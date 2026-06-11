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
        list_width = 520
        padding = 22
        row_height = 92
        canvas_height = max(base.height, padding * 2 + 54 + max(1, len(annotations)) * row_height)
        canvas = Image.new("RGBA", (base.width + list_width, canvas_height), (248, 250, 252, 255))
        canvas.paste(base.convert("RGBA"), (0, 0))
        draw = ImageDraw.Draw(canvas)
        font = self._load_font(18)
        small = self._load_font(15)
        strong = self._load_font(20)
        canvas.info["bubble_font"] = self._font_name(font)

        draw.rounded_rectangle(
            (base.width + 12, 14, canvas.width - 14, canvas.height - 14),
            radius=10,
            fill=(255, 255, 255, 255),
            outline=(220, 226, 233, 255),
            width=1,
        )
        draw.text((base.width + padding, padding), "图纸标注审阅", fill=(25, 31, 39, 255), font=strong)
        draw.text(
            (base.width + padding, padding + 28),
            f"{len(annotations)} 条结构化标注",
            fill=(100, 116, 139, 255),
            font=small,
        )

        if not annotations:
            draw.text((base.width + padding, padding + 62), "未识别到可绘制标注", fill=(100, 116, 139, 255), font=font)
            return canvas.convert("RGB")

        for index, annotation in enumerate(annotations, start=1):
            label = annotation.label or annotation.annotation_id or f"A{index:03d}"
            color = self._color(index)
            if self._has_valid_region(annotation):
                x1, y1, x2, y2 = self._region_to_pixels(annotation, base.width, base.height)
                self._draw_annotation_callout(
                    draw,
                    annotation,
                    label,
                    (x1, y1, x2, y2),
                    base.width,
                    color,
                    font,
                    small,
                )

            row_y = padding + 62 + (index - 1) * row_height
            if row_y > canvas.height - 70:
                continue
            text = self._safe_text(annotation.parameter_name or annotation.normalized_text or annotation.raw_text or label)
            value = self._safe_text(annotation.parameter_value or annotation.normalized_text or annotation.raw_text or "待确认")
            status = self._status_label(annotation.review_status)
            summary = self._annotation_summary(annotation)
            card_x1 = base.width + padding
            card_y1 = row_y
            card_x2 = canvas.width - padding
            card_y2 = min(canvas.height - 24, row_y + row_height - 10)
            draw.rounded_rectangle(
                (card_x1, card_y1, card_x2, card_y2),
                radius=8,
                fill=(248, 250, 252, 255),
                outline=(226, 232, 240, 255),
                width=1,
            )
            draw.rounded_rectangle(
                (card_x1 + 12, card_y1 + 14, card_x1 + 58, card_y1 + 38),
                radius=6,
                fill=color + (24,),
                outline=color + (190,),
                width=1,
            )
            draw.text((card_x1 + 20, card_y1 + 18), self._short_label(label, index), fill=color + (255,), font=small)
            draw.text((card_x1 + 68, card_y1 + 12), self._fit_text(text, 32), fill=(15, 23, 42, 255), font=strong)
            draw.text((card_x1 + 68, card_y1 + 38), f"值：{self._fit_text(value, 24)}  状态：{status}", fill=(71, 85, 105, 255), font=font)
            for line_index, line in enumerate(self._wrap_text(summary, 38)[:2]):
                draw.text((card_x1 + 68, card_y1 + 63 + line_index * 18), line, fill=(100, 116, 139, 255), font=small)
        result = canvas.convert("RGB")
        result.info["bubble_font"] = canvas.info.get("bubble_font", "unknown")
        return result

    def _draw_annotation_callout(
        self,
        draw: ImageDraw.ImageDraw,
        annotation: DrawingAnnotation,
        label: str,
        region: tuple[int, int, int, int],
        page_width: int,
        color: tuple[int, int, int],
        font,
        small,
    ) -> None:
        x1, y1, x2, y2 = region
        rgba = color + (255,)
        fill = color + (28,)
        outline = color + (185,)
        draw.rounded_rectangle((x1, y1, x2, y2), radius=4, fill=fill, outline=outline, width=2)

        value = self._safe_text(annotation.parameter_value or annotation.normalized_text or annotation.raw_text or label)
        title = self._fit_text(f"{self._short_label(label, 0)}  {value}", 18)
        text_box = draw.textbbox((0, 0), title, font=small)
        tag_width = min(max(text_box[2] - text_box[0] + 22, 82), 260)
        tag_height = 30
        tag_x = x2 + 12 if x2 + tag_width + 18 < page_width else max(8, x1 - tag_width - 12)
        tag_y = max(8, min(y1 - 6, y2 - tag_height + 6))
        anchor_x = x2 if tag_x > x2 else x1
        anchor_y = max(y1, min(y2, tag_y + tag_height // 2))

        draw.line((anchor_x, anchor_y, tag_x if tag_x > x2 else tag_x + tag_width, tag_y + tag_height // 2), fill=rgba, width=2)
        draw.rounded_rectangle(
            (tag_x, tag_y, tag_x + tag_width, tag_y + tag_height),
            radius=8,
            fill=(255, 255, 255, 238),
            outline=outline,
            width=1,
        )
        draw.rounded_rectangle((tag_x, tag_y, tag_x + 8, tag_y + tag_height), radius=4, fill=rgba)
        draw.text((tag_x + 14, tag_y + 7), title, fill=(15, 23, 42, 255), font=small)

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

    def _short_label(self, label: str, index: int) -> str:
        text = self._safe_text(label).strip()
        if not text or len(text) > 6:
            return f"A{index:02d}" if index else text[:6] or "A"
        return text

    def _fit_text(self, value: str, max_chars: int) -> str:
        text = self._safe_text(value)
        if len(text) <= max_chars:
            return text
        return text[: max(1, max_chars - 1)].rstrip() + "…"

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
