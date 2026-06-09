from __future__ import annotations

import base64
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
        if suffix in {".dwg", ".dxf"}:
            return self.parse_vector_placeholder(path)
        return DrawingParseResult(
            risk_flags=[RiskFlag(field="file", message=f"暂不支持的文件格式：{suffix}", severity="critical")]
        )

    def parse_pdf(self, path: Path) -> DrawingParseResult:
        raw_text = self._extract_pdf_text(path)
        result = self.parse_text(raw_text)
        result.raw_text = raw_text
        if not raw_text.strip():
            result.risk_flags.append(
                RiskFlag(field="raw_text", message="PDF 未提取到文本，需要接入 OCR 或多模态识图", severity="warning")
            )
        return result

    def parse_image(self, path: Path) -> DrawingParseResult:
        return DrawingParseResult(
            raw_text="",
            risk_flags=[
                RiskFlag(field="image", message="图片输入已接收，当前 MVP 未接入 OCR/多模态识别，需要人工确认", severity="warning")
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
            page_texts = [page.extract_text() or "" for page in reader.pages[:3]]
            return "\n".join(page_texts)
        except Exception:
            return ""

    def extract_pdf_page_images(self, path: str | Path, max_images: int = 1, zoom: float = 1.0) -> list[dict[str, str]]:
        try:
            import fitz
        except Exception:
            return []

        images: list[dict[str, str]] = []
        document = fitz.open(str(path))
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