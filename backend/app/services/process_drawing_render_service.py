from __future__ import annotations

import html
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.models.process_drawing import ProcessDrawingAsset, ProcessDrawingPlan, ProcessDrawingSheet
from app.services.engineering_text import normalize_engineering_text


class ProcessDrawingRenderService:
    """Render deterministic draft process drawings from ProcessDrawingPlan."""

    width = 1400
    height = 900

    def render(self, plan: ProcessDrawingPlan, target_dir: str | Path) -> ProcessDrawingPlan:
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        json_name = "process_drawing_plan.json"
        json_path = target / json_name

        for sheet in plan.sheets:
            self._render_sheet(plan, sheet, target)

        plan.assets.append(
            ProcessDrawingAsset(
                asset_type="json",
                file_name=json_name,
                file_path=str(json_path),
                file_url=f"process_drawings/{json_name}",
                status="generated",
                message="工艺图计划 JSON 已生成",
            )
        )
        json_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        return plan

    def _render_sheet(self, plan: ProcessDrawingPlan, sheet: ProcessDrawingSheet, target: Path) -> None:
        base_name = f"{sheet.sheet_no.lower()}_process_drawing"
        svg_name = f"{base_name}.svg"
        png_name = f"{base_name}.png"
        svg_path = target / svg_name
        png_path = target / png_name
        svg = self._sheet_svg(plan, sheet)
        svg_path.write_text(svg, encoding="utf-8")
        self._sheet_png(plan, sheet, png_path)
        sheet.assets.extend(
            [
                ProcessDrawingAsset(
                    asset_type="svg",
                    file_name=svg_name,
                    file_path=str(svg_path),
                    file_url=f"process_drawings/{svg_name}",
                    width=self.width,
                    height=self.height,
                    status="generated",
                    message="SVG 工艺图草稿已生成",
                ),
                ProcessDrawingAsset(
                    asset_type="png",
                    file_name=png_name,
                    file_path=str(png_path),
                    file_url=f"process_drawings/{png_name}",
                    width=self.width,
                    height=self.height,
                    status="generated",
                    message="PNG 工艺图草稿已生成",
                ),
            ]
        )

    def _sheet_svg(self, plan: ProcessDrawingPlan, sheet: ProcessDrawingSheet) -> str:
        title = self._safe(sheet.title)
        part_name = self._safe(plan.part_name or plan.title)
        drawing_no = self._safe(plan.drawing_no or "待确认")
        summary = self._safe(sheet.summary or "工艺图草稿")
        operations = [self._safe(item) for item in sheet.related_operation_nos[:8]]
        op_callouts = [item for item in sheet.callouts if item.position.get("zone") == "operation"][:6]
        notes = [self._safe(item) for item in sheet.notes[:6]]

        callout_svg = []
        for index, callout in enumerate(op_callouts, start=1):
            x = 150 + (index - 1) * 180
            y = 560 if index % 2 else 245
            anchor_x = 260 + (index - 1) * 150
            anchor_y = 420 if index % 2 else 390
            callout_svg.append(
                f'<line x1="{anchor_x}" y1="{anchor_y}" x2="{x}" y2="{y}" stroke="#111" stroke-width="1" />'
                f'<rect x="{x}" y="{y}" width="150" height="44" fill="#fff" stroke="#111" stroke-width="1" />'
                f'<text x="{x + 10}" y="{y + 18}" font-size="13" font-weight="700">{self._safe(callout.label)}</text>'
                f'<text x="{x + 10}" y="{y + 36}" font-size="12">{self._safe(callout.text)[:16]}</text>'
            )

        note_rows = []
        for index, note in enumerate(notes, start=1):
            note_rows.append(f'<text x="80" y="{690 + index * 26}" font-size="14">{index}. {note[:62]}</text>')

        op_rows = []
        for index, operation_no in enumerate(operations, start=1):
            op_rows.append(f'<text x="1040" y="{626 + index * 24}" font-size="13">{index}. OP{operation_no}</text>')

        return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" viewBox="0 0 {self.width} {self.height}">
  <rect width="100%" height="100%" fill="#fff" />
  <rect x="35" y="35" width="1330" height="830" fill="none" stroke="#111" stroke-width="1.5" />
  <rect x="55" y="55" width="1290" height="790" fill="none" stroke="#111" stroke-width="0.8" />
  <text x="70" y="90" font-size="20" font-weight="700">{title}</text>
  <text x="70" y="120" font-size="13">{summary}</text>
  <line x1="110" y1="405" x2="1040" y2="405" stroke="#777" stroke-width="1" stroke-dasharray="12 8" />
  <polyline points="130,405 180,370 245,370 275,405 325,405 355,350 420,350 455,405 515,405 545,350 610,350 645,405 705,405 740,370 805,370 850,405 1000,405" fill="none" stroke="#111" stroke-width="2" />
  <polyline points="130,405 180,440 245,440 275,405 325,405 355,460 420,460 455,405 515,405 545,460 610,460 645,405 705,405 740,440 805,440 850,405 1000,405" fill="none" stroke="#111" stroke-width="2" />
  <rect x="78" y="620" width="860" height="205" fill="none" stroke="#111" stroke-width="1" />
  <text x="90" y="650" font-size="16" font-weight="700">技术要求 / 复核提示</text>
  {''.join(note_rows)}
  <rect x="1010" y="590" width="300" height="235" fill="none" stroke="#111" stroke-width="1" />
  <text x="1030" y="620" font-size="16" font-weight="700">关联工序</text>
  {''.join(op_rows)}
  {''.join(callout_svg)}
  <rect x="980" y="735" width="330" height="90" fill="none" stroke="#111" stroke-width="1" />
  <line x1="980" y1="765" x2="1310" y2="765" stroke="#111" stroke-width="1" />
  <line x1="1085" y1="735" x2="1085" y2="825" stroke="#111" stroke-width="1" />
  <text x="995" y="756" font-size="12">零件名称</text>
  <text x="1100" y="756" font-size="12">{part_name[:24]}</text>
  <text x="995" y="788" font-size="12">图号</text>
  <text x="1100" y="788" font-size="12">{drawing_no[:24]}</text>
  <text x="995" y="815" font-size="12">阶段</text>
  <text x="1100" y="815" font-size="12">{self._safe(sheet.stage)}</text>
</svg>'''

    def _sheet_png(self, plan: ProcessDrawingPlan, sheet: ProcessDrawingSheet, output_path: Path) -> None:
        image = Image.new("RGB", (self.width, self.height), "white")
        draw = ImageDraw.Draw(image)
        font = self._font(16)
        small = self._font(13)
        title_font = self._font(22)
        draw.rectangle((35, 35, 1365, 865), outline="#111111", width=2)
        draw.rectangle((55, 55, 1345, 845), outline="#111111", width=1)
        draw.text((70, 70), normalize_engineering_text(sheet.title), fill="#111111", font=title_font)
        draw.text((70, 104), normalize_engineering_text(sheet.summary), fill="#333333", font=small)
        draw.line((110, 405, 1040, 405), fill="#777777", width=1)
        upper = [(130, 405), (180, 370), (245, 370), (275, 405), (325, 405), (355, 350), (420, 350), (455, 405), (515, 405), (545, 350), (610, 350), (645, 405), (705, 405), (740, 370), (805, 370), (850, 405), (1000, 405)]
        lower = [(130, 405), (180, 440), (245, 440), (275, 405), (325, 405), (355, 460), (420, 460), (455, 405), (515, 405), (545, 460), (610, 460), (645, 405), (705, 405), (740, 440), (805, 440), (850, 405), (1000, 405)]
        draw.line(upper, fill="#111111", width=2)
        draw.line(lower, fill="#111111", width=2)

        op_callouts = [item for item in sheet.callouts if item.position.get("zone") == "operation"][:6]
        for index, callout in enumerate(op_callouts, start=1):
            x = 150 + (index - 1) * 180
            y = 560 if index % 2 else 245
            anchor_x = 260 + (index - 1) * 150
            anchor_y = 420 if index % 2 else 390
            draw.line((anchor_x, anchor_y, x, y), fill="#111111", width=1)
            draw.rectangle((x, y, x + 150, y + 44), fill="white", outline="#111111", width=1)
            draw.text((x + 10, y + 6), normalize_engineering_text(callout.label), fill="#111111", font=small)
            draw.text((x + 10, y + 24), normalize_engineering_text(callout.text)[:16], fill="#111111", font=small)

        draw.rectangle((78, 620, 938, 825), outline="#111111", width=1)
        draw.text((90, 635), "技术要求 / 复核提示", fill="#111111", font=font)
        for index, note in enumerate(sheet.notes[:6], start=1):
            draw.text((90, 662 + index * 24), f"{index}. {normalize_engineering_text(note)[:62]}", fill="#111111", font=small)

        draw.rectangle((1010, 590, 1310, 825), outline="#111111", width=1)
        draw.text((1030, 605), "关联工序", fill="#111111", font=font)
        for index, operation_no in enumerate(sheet.related_operation_nos[:8], start=1):
            draw.text((1040, 626 + index * 24), f"{index}. OP{operation_no}", fill="#111111", font=small)

        draw.rectangle((980, 735, 1310, 825), outline="#111111", width=1)
        draw.line((980, 765, 1310, 765), fill="#111111", width=1)
        draw.line((1085, 735, 1085, 825), fill="#111111", width=1)
        draw.text((995, 744), "零件名称", fill="#111111", font=small)
        draw.text((1100, 744), normalize_engineering_text(plan.part_name or plan.title)[:24], fill="#111111", font=small)
        draw.text((995, 776), "图号", fill="#111111", font=small)
        draw.text((1100, 776), normalize_engineering_text(plan.drawing_no or "待确认")[:24], fill="#111111", font=small)
        draw.text((995, 803), "阶段", fill="#111111", font=small)
        draw.text((1100, 803), str(sheet.stage), fill="#111111", font=small)
        image.save(output_path)

    def _safe(self, value: object) -> str:
        return html.escape(normalize_engineering_text(str(value or "")))

    def _font(self, size: int):
        candidates = [
            "/System/Library/Fonts/PingFang.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simfang.ttf",
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


process_drawing_render_service = ProcessDrawingRenderService()