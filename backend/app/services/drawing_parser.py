from __future__ import annotations

import base64
import re
from pathlib import Path

from pypdf import PdfReader

from app.models.drawing import (
    ConfidenceLevel,
    DrawingFeature,
    DrawingParseResult,
    FeatureType,
    InspectionRequirement,
    PartInfo,
    RequirementType,
    RiskFlag,
    TechnicalRequirement,
)
from app.rules.crankshaft_rules import REQUIREMENT_RULES
from app.services.ocr_service import ocr_service


FEATURE_KEYWORDS: dict[FeatureType, tuple[str, ...]] = {
    FeatureType.MAIN_JOURNAL: ("主轴颈", "主轴径"),
    FeatureType.ROD_JOURNAL: ("连杆颈", "连杆径"),
    FeatureType.FLANGE: ("法兰", "法兰端"),
    FeatureType.OIL_HOLE: ("油孔", "油道"),
    FeatureType.BOLT_HOLE: ("螺栓孔", "安装孔"),
    FeatureType.DOWEL_HOLE: ("定位销孔", "销孔"),
    FeatureType.COUNTERWEIGHT: ("平衡块",),
    FeatureType.MARKING_AREA: ("打刻", "标识区"),
    FeatureType.NO_CHAMFER_AREA: ("无倒角", "不得倒角"),
}


class DrawingParser:
    def parse_file(self, file_path: str | Path) -> DrawingParseResult:
        path = Path(file_path)
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return self.parse_pdf(path)
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            return self.parse_image(path)
        if suffix == ".dxf":
            return self.parse_dxf(path)
        if suffix == ".dwg":
            return self.parse_dwg(path)
        return DrawingParseResult(
            risk_flags=[RiskFlag(field="file", message=f"暂不支持的文件格式：{suffix}", severity="critical")]
        )

    def parse_pdf(self, path: Path) -> DrawingParseResult:
        raw_text = self._extract_pdf_text(path)
        if len(raw_text.strip()) < 100:
            ocr_text = ocr_service.extract_text_from_pdf(path)
            if ocr_text.strip():
                raw_text = f"{raw_text.strip()}\n\n{ocr_text.strip()}" if raw_text.strip() else ocr_text.strip()
        result = self.parse_text(raw_text)
        result.raw_text = raw_text
        if not raw_text.strip():
            result.risk_flags.append(
                RiskFlag(field="raw_text", message="PDF 未提取到文本，需要接入 OCR 或多模态识图", severity="warning")
            )
        return result

    def parse_image(self, path: Path) -> DrawingParseResult:
        text = ocr_service.extract_text_from_image(path)
        if text.strip():
            result = self.parse_text(text)
            result.raw_text = text
            result.risk_flags.append(
                RiskFlag(field="image_ocr", message="图片已通过 OCR 提取文字，仍建议人工确认关键标注", severity="info")
            )
            return result
        return DrawingParseResult(
            raw_text="",
            risk_flags=[
                RiskFlag(field="image", message="图片输入已接收，当前 OCR 未识别到足够文字，需要人工确认", severity="warning")
            ],
        )

    def parse_dxf(self, path: Path) -> DrawingParseResult:
        text = self._extract_dxf_text(path)
        if not text.strip():
            text = self._extract_dxf_text_with_ezdxf(path)
        if text.strip():
            result = self.parse_text(text)
            result.raw_text = text
            result.risk_flags.append(
                RiskFlag(field="dxf", message="DXF 已解析文本/标注实体，几何预览由 CAD 渲染链路生成", severity="info")
            )
            return result
        return DrawingParseResult(
            raw_text="",
            risk_flags=[
                RiskFlag(field="vector_drawing", message="DXF 未提取到可读文本，请检查文件或安装 ezdxf", severity="warning")
            ],
        )

    def parse_dwg(self, path: Path) -> DrawingParseResult:
        text = self._extract_dwg_text_with_odafc(path)
        if text.strip():
            result = self.parse_text(text)
            result.raw_text = text
            result.risk_flags.append(
                RiskFlag(field="dwg", message="DWG 已通过 ODA 转换读取文本，几何预览依赖 CAD 渲染链路", severity="info")
            )
            return result
        return DrawingParseResult(
            raw_text="",
            risk_flags=[
                RiskFlag(
                    field="vector_drawing",
                    message="DWG 未解析到文本；安装 ODA File Converter 后可渲染并提取更多内容",
                    severity="warning",
                )
            ],
        )

    def parse_vector_placeholder(self, path: Path) -> DrawingParseResult:
        return DrawingParseResult(
            raw_text="",
            risk_flags=[
                RiskFlag(field="vector_drawing", message="DWG/DXF 输入已接收，当前版本仅预留解析入口，不执行 CAD 生成", severity="warning")
            ],
        )

    def parse_text(self, text: str) -> DrawingParseResult:
        features = self._extract_features(text)
        technical_requirements = self._extract_requirements(text)
        inspection_requirements = self._extract_inspection_requirements(text)
        risk_flags = []
        if not features:
            risk_flags.append(RiskFlag(field="features", message="未识别到明确曲轴加工特征", severity="warning"))
        if not technical_requirements:
            risk_flags.append(RiskFlag(field="technical_requirements", message="未识别到明确技术要求", severity="warning"))

        return DrawingParseResult(
            part=PartInfo(part_name="曲轴" if "曲轴" in text else None),
            features=features,
            technical_requirements=technical_requirements,
            inspection_requirements=inspection_requirements,
            risk_flags=risk_flags,
            raw_text=text,
        )

    def _extract_pdf_text(self, path: Path) -> str:
        try:
            reader = PdfReader(str(path), strict=False)
            page_texts = [page.extract_text() or "" for page in reader.pages]
            return "\n".join(page_texts)
        except Exception:
            return ""

    def _extract_dxf_text(self, path: Path) -> str:
        try:
            raw = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""

        lines = [line.rstrip("\r") for line in raw.splitlines() if line.strip()]
        if len(lines) < 4:
            return ""

        texts: list[str] = []
        current_entity = ""
        pair_count = len(lines) - len(lines) % 2
        for index in range(0, pair_count, 2):
            code = lines[index].strip()
            value = lines[index + 1].strip()
            if code == "0":
                current_entity = value.upper()
                continue
            if code == "1" and current_entity in {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"} and value:
                texts.append(value)

        if texts:
            unique_texts: list[str] = []
            seen = set()
            for item in texts:
                normalized = item.strip()
                if normalized and normalized not in seen:
                    unique_texts.append(normalized)
                    seen.add(normalized)
            return "\n".join(unique_texts)

        keyword_hits = [line.strip() for line in lines if line.strip() and any(token in line for token in ("曲轴", "公差", "粗糙度", "材料", "热处理"))]
        return "\n".join(keyword_hits[:20])

    def _extract_dxf_text_with_ezdxf(self, path: Path) -> str:
        try:
            import ezdxf
        except Exception:
            return ""
        try:
            document = ezdxf.readfile(str(path))
        except Exception:
            return ""
        texts: list[str] = []
        for entity in document.modelspace().query("TEXT MTEXT ATTRIB ATTDEF"):
            value = getattr(entity.dxf, "text", "") or ""
            if value.strip():
                texts.append(value.strip())
        return "\n".join(dict.fromkeys(texts))

    def _extract_dwg_text_with_odafc(self, path: Path) -> str:
        try:
            from ezdxf.addons import odafc
        except Exception:
            return ""
        if not odafc.is_installed():
            return ""
        try:
            document = odafc.readfile(str(path))
        except Exception:
            return ""
        texts: list[str] = []
        for entity in document.modelspace().query("TEXT MTEXT ATTRIB ATTDEF"):
            value = getattr(entity.dxf, "text", "") or ""
            if value.strip():
                texts.append(value.strip())
        return "\n".join(dict.fromkeys(texts))

    def extract_pdf_page_images(self, path: str | Path, max_images: int = 6, zoom: float = 1.5) -> list[dict[str, str]]:
        try:
            import fitz
        except Exception:
            return []

        images: list[dict[str, str]] = []
        try:
            document = fitz.open(str(path))
        except Exception:
            return []
        try:
            matrix = fitz.Matrix(zoom, zoom)
            for page_index in range(min(len(document), max_images)):
                page = document.load_page(page_index)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                data = pixmap.tobytes("png")
                images.append(
                    {
                        "name": f"page_{page_index + 1}.png",
                        "page": str(page_index + 1),
                        "mime_type": "image/png",
                        "base64": base64.b64encode(data).decode("ascii"),
                        "source": "pdf_page_image",
                    }
                )
        finally:
            document.close()
        return images

    def extract_pdf_images(self, path: str | Path, max_images: int = 6) -> list[dict[str, str]]:
        reader = PdfReader(str(path))
        images: list[dict[str, str]] = []
        for page_index, page in enumerate(reader.pages, start=1):
            for image_index, image in enumerate(page.images, start=1):
                if len(images) >= max_images:
                    return images
                data = image.data
                suffix = Path(image.name).suffix.lower()
                mime_type = "image/png"
                if suffix in {".jpg", ".jpeg"}:
                    mime_type = "image/jpeg"
                elif suffix == ".webp":
                    mime_type = "image/webp"
                images.append(
                    {
                        "name": image.name or f"page_{page_index}_image_{image_index}",
                        "page": str(page_index),
                        "mime_type": mime_type,
                        "base64": base64.b64encode(data).decode("ascii"),
                    }
                )
        return images

    def _extract_features(self, text: str) -> list[DrawingFeature]:
        features: list[DrawingFeature] = []
        for feature_type, keywords in FEATURE_KEYWORDS.items():
            matched = [keyword for keyword in keywords if keyword in text]
            if matched:
                features.append(
                    DrawingFeature(
                        type=feature_type,
                        name=matched[0],
                        description=f"图纸文本中识别到{matched[0]}相关加工特征",
                        source_text="、".join(matched),
                        confidence=ConfidenceLevel.HIGH,
                    )
                )
        return features

    def _extract_requirements(self, text: str) -> list[TechnicalRequirement]:
        requirements: list[TechnicalRequirement] = []
        for requirement_type, rule in REQUIREMENT_RULES.items():
            matched = [keyword for keyword in rule["keywords"] if keyword in text]
            if matched:
                requirements.append(
                    TechnicalRequirement(
                        type=requirement_type,
                        content=rule["control_point"],
                        source_text="、".join(matched),
                        confidence=ConfidenceLevel.HIGH,
                    )
                )
        return requirements

    def _extract_inspection_requirements(self, text: str) -> list[InspectionRequirement]:
        items: list[InspectionRequirement] = []
        inspection_keywords = ("检测", "检验", "测量", "终检", "探伤", "动平衡")
        for keyword in inspection_keywords:
            if keyword in text:
                items.append(
                    InspectionRequirement(
                        item=keyword,
                        method=None,
                        acceptance=None,
                        source_text=keyword,
                        confidence=ConfidenceLevel.MEDIUM,
                    )
                )
        return items