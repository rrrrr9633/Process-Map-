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
        canvas = base.convert("RGBA")
        draw = ImageDraw.Draw(canvas)
        font = self._load_font(14)
        canvas.info["bubble_font"] = self._font_name(font)

        drawable_annotations = [annotation for annotation in annotations if self._has_valid_region(annotation)]
        if not drawable_annotations:
            result = canvas.convert("RGB")
            result.info["bubble_font"] = canvas.info.get("bubble_font", "unknown")
            return result

        occupied_boxes: list[tuple[int, int, int, int]] = []
        for index, annotation in enumerate(drawable_annotations, start=1):
            label = annotation.label or annotation.annotation_id or f"A{index:03d}"
            color = self._semantic_color(annotation.semantic_type, index)
            region = self._region_to_pixels(annotation, base.width, base.height)
            self._draw_annotation_callout(
                draw,
                annotation,
                label,
                region,
                base.width,
                base.height,
                color,
                font,
                occupied_boxes,
            )

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
        page_height: int,
        color: tuple[int, int, int],
        font,
        occupied_boxes: list[tuple[int, int, int, int]],
    ) -> None:
        x1, y1, x2, y2 = region
        rgba = color + (235,)
        anchor_x = (x1 + x2) // 2
        anchor_y = (y1 + y2) // 2
        target_radius = 3
        draw.ellipse(
            (anchor_x - target_radius, anchor_y - target_radius, anchor_x + target_radius, anchor_y + target_radius),
            fill=(255, 255, 255, 245),
            outline=rgba,
            width=1,
        )

        title = self._bubble_title(annotation, label)
        text_box = draw.textbbox((0, 0), title, font=font)
        text_width = text_box[2] - text_box[0]
        text_height = text_box[3] - text_box[1]
        padding_x = 8
        padding_y = 5
        tag_width = min(max(text_width + padding_x * 2, 58), min(210, max(80, page_width // 3)))
        tag_height = text_height + padding_y * 2
        gap = 18

        candidates = self._label_candidates(anchor_x, anchor_y, tag_width, tag_height, page_width, page_height, gap)
        tag_x, tag_y = self._choose_label_position(candidates, tag_width, tag_height, occupied_boxes, page_width, page_height)
        tag_box = (tag_x, tag_y, tag_x + tag_width, tag_y + tag_height)
        occupied_boxes.append(tag_box)

        connector_x = tag_x if tag_x > anchor_x else tag_x + tag_width
        connector_y = tag_y + tag_height // 2
        draw.line((anchor_x, anchor_y, connector_x, connector_y), fill=rgba, width=1)
        draw.rounded_rectangle(
            tag_box,
            radius=4,
            fill=(255, 255, 255, 242),
            outline=color + (210,),
            width=1,
        )
        draw.line((tag_x + 5, tag_y + tag_height - 1, tag_x + tag_width - 5, tag_y + tag_height - 1), fill=color + (105,), width=1)
        draw.text((tag_x + padding_x, tag_y + padding_y - 1), self._fit_text(title, 18), fill=(31, 41, 55, 255), font=font)

    def _bubble_title(self, annotation: DrawingAnnotation, label: str) -> str:
        short_label = self._short_label(label, 0)
        value = self._safe_text(annotation.parameter_value or annotation.normalized_text or annotation.raw_text or "")
        if value and value != short_label:
            return f"{short_label} {self._fit_text(value, 12)}"
        return short_label

    def _label_candidates(
        self,
        anchor_x: int,
        anchor_y: int,
        tag_width: int,
        tag_height: int,
        page_width: int,
        page_height: int,
        gap: int,
    ) -> list[tuple[int, int]]:
        positions = [
            (anchor_x + gap, anchor_y - tag_height - 6),
            (anchor_x + gap, anchor_y + 6),
            (anchor_x - tag_width - gap, anchor_y - tag_height - 6),
            (anchor_x - tag_width - gap, anchor_y + 6),
            (anchor_x - tag_width // 2, anchor_y - tag_height - gap),
            (anchor_x - tag_width // 2, anchor_y + gap),
        ]
        clamped: list[tuple[int, int]] = []
        margin = 6
        for x, y in positions:
            clamped.append(
                (
                    max(margin, min(page_width - tag_width - margin, x)),
                    max(margin, min(page_height - tag_height - margin, y)),
                )
            )
        return clamped

    def _choose_label_position(
        self,
        candidates: list[tuple[int, int]],
        tag_width: int,
        tag_height: int,
        occupied_boxes: list[tuple[int, int, int, int]],
        page_width: int,
        page_height: int,
    ) -> tuple[int, int]:
        if not candidates:
            return 6, 6

        best = candidates[0]
        best_score = -1
        for x, y in candidates:
            score = 100
            probe = (x, y, x + tag_width, y + tag_height)
            for occupied in occupied_boxes:
                if self._boxes_overlap(probe, occupied, padding=5):
                    score -= 45
            if x <= 8 or y <= 8 or x + tag_width >= page_width - 8 or y + tag_height >= page_height - 8:
                score -= 10
            if score > best_score:
                best = (x, y)
                best_score = score
        return best

    def _boxes_overlap(
        self,
        first: tuple[int, int, int, int],
        second: tuple[int, int, int, int],
        padding: int = 0,
    ) -> bool:
        return not (
            first[2] + padding < second[0]
            or first[0] - padding > second[2]
            or first[3] + padding < second[1]
            or first[1] - padding > second[3]
        )

    def _semantic_color(self, semantic_type: str, index: int) -> tuple[int, int, int]:
        colors = {
            "dimension": (55, 65, 81),
            "tolerance": (37, 99, 235),
            "roughness": (5, 150, 105),
            "datum": (124, 58, 237),
            "geometric_tolerance": (2, 132, 199),
            "material": (146, 64, 14),
            "process_note": (190, 18, 60),
            "inspection_note": (14, 116, 144),
            "quality_note": (180, 83, 9),
            "unknown": self._color(index),
        }
        return colors.get(semantic_type, self._color(index))

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
