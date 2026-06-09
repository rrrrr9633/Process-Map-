from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from PIL import Image
from pydantic import ValidationError

from app.config import settings
from app.models.annotation import AnnotationExportRow, DrawingAnnotation, DrawingAnnotationResult
from app.models.drawing_explanation import DrawingExplanation, DrawingPageAsset, DrawingPageExplanation, DrawingViewExplanation
from app.services.ai_service import AIServiceError, ai_service
from app.services.annotation_normalizer import map_view_local_regions_to_page, merge_annotation_results, normalize_annotation_result
from app.services.cad_render_service import cad_render_service
from app.services.drawing_parser import DrawingParser
from app.services.ocr_service import ocr_service
from app.services.sheet_view_splitter import SheetViewRegion, crop_view_payload, split_sheet_views


class DrawingExplanationService:
    def __init__(self) -> None:
        self._parser = DrawingParser()

    def render_all_pages(
        self,
        source_path: str | Path,
        target_dir: str | Path,
        file_index: int,
        file_name: str,
    ) -> list[tuple[int, DrawingPageAsset, dict[str, str], str]]:
        path = Path(source_path)
        suffix = path.suffix.lower()
        max_pages = settings.agent_max_pdf_pages
        pages: list[tuple[int, DrawingPageAsset, dict[str, str], str]] = []

        if suffix == ".pdf":
            pages.extend(self._render_pdf_pages(path, target_dir, file_index, file_name, max_pages))
        elif suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            item = self._render_image_page(path, target_dir, file_index, file_name, page=1)
            if item:
                pages.append(item)
        elif suffix in {".dxf", ".dwg"}:
            for asset, payload in cad_render_service.render_pages(
                path, target_dir, file_index, file_name, max_pages=max_pages
            ):
                page = asset.page
                ocr_text = ocr_service.extract_text_from_image(Path(asset.image_path))
                pages.append((page, asset, payload, ocr_text))
        return pages


    def _count_pdf_pages(self, path: Path) -> int:
        try:
            import fitz
        except Exception:
            return 0
        document = fitz.open(str(path))
        try:
            return len(document)
        finally:
            document.close()

    def _render_pdf_pages(
        self,
        path: Path,
        target_dir: str | Path,
        file_index: int,
        file_name: str,
        max_pages: int,
    ) -> list[tuple[int, DrawingPageAsset, dict[str, str], str]]:
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        page_texts = ocr_service.extract_pdf_page_texts(path, max_pages=max_pages)
        rendered: list[tuple[int, DrawingPageAsset, dict[str, str], str]] = []
        try:
            import fitz
        except Exception:
            return rendered

        document = fitz.open(str(path))
        try:
            total = min(len(document), max_pages)
            matrix = fitz.Matrix(1.5, 1.5)
            for page_index in range(total):
                page_no = page_index + 1
                image_path = target / f"file_{file_index:03d}_page_{page_no}.png"
                page = document.load_page(page_index)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                image_path.write_bytes(pixmap.tobytes("png"))
                with Image.open(image_path) as image:
                    width, height = image.size
                payload = {
                    "name": image_path.name,
                    "page": str(page_no),
                    "mime_type": "image/png",
                    "base64": base64.b64encode(image_path.read_bytes()).decode("ascii"),
                    "source": "pdf_page_image",
                }
                asset = DrawingPageAsset(
                    file_index=file_index,
                    file_name=file_name,
                    page=page_no,
                    image_path=str(image_path),
                    image_url=f"pages/{image_path.name}",
                    width=width,
                    height=height,
                )
                ocr_text = page_texts.get(page_no, "")
                if len(ocr_text.strip()) < 20:
                    ocr_text = (ocr_text + "\n" + ocr_service.extract_text_from_image(image_path)).strip()
                rendered.append((page_no, asset, payload, ocr_text))
        finally:
            document.close()
        return rendered

    def _render_image_page(
        self,
        path: Path,
        target_dir: str | Path,
        file_index: int,
        file_name: str,
        *,
        page: int,
    ) -> tuple[int, DrawingPageAsset, dict[str, str], str] | None:
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        image_path = target / f"file_{file_index:03d}_page_{page}.png"
        try:
            image = Image.open(path).convert("RGB")
            image.save(image_path)
            with Image.open(image_path) as saved:
                width, height = saved.size
            payload = {
                "name": image_path.name,
                "page": str(page),
                "mime_type": "image/png",
                "base64": base64.b64encode(image_path.read_bytes()).decode("ascii"),
                "source": "pdf_page_image",
            }
            asset = DrawingPageAsset(
                file_index=file_index,
                file_name=file_name,
                page=page,
                image_path=str(image_path),
                image_url=f"pages/{image_path.name}",
                width=width,
                height=height,
            )
            ocr_text = ocr_service.extract_text_from_image(image_path)
            return page, asset, payload, ocr_text
        except Exception:
            return None

    async def explain_file(self, source_path: str | Path, target_dir: str | Path, file_index: int) -> DrawingExplanation:
        path = Path(source_path)
        pages = self.render_all_pages(path, target_dir, file_index, path.name)
        explanation = DrawingExplanation(
            file_index=file_index,
            file_name=path.name,
            source_path=str(path),
            page_count=max(1, len(pages)),
            visual_summary="等待 AI 逐页图解" if pages else "该文件暂无法生成页面预览",
            detected_features=[],
            related_operations=[f"第 {file_index} 份图纸"],
            risk_notes=[] if pages else ["暂不支持该文件类型的图解预览"],
        )
        if not pages:
            raise AIServiceError(f"第 {file_index} 份图纸无法生成可识别页面：{path.name}")
        if not ai_service.enabled:
            raise AIServiceError("AI Agent 未启用：未配置 AI_API_KEY")

        page_explanations: list[DrawingPageExplanation] = []
        max_views = settings.agent_max_views_per_page
        for page_no, page_asset, image_payload, ocr_text in pages:
            image_path = Path(page_asset.image_path) if page_asset and page_asset.image_path else None
            view_regions: list[SheetViewRegion] = (
                split_sheet_views(image_path, max_views=max_views) if image_path and image_path.is_file() else [SheetViewRegion(1, "整页", 0.0, 0.0, 1.0, 1.0)]
            )
            if len(view_regions) <= 1:
                payload = await ai_service.explain_single_drawing_page(
                    file_name=path.name,
                    file_index=file_index,
                    page=page_no,
                    page_count=explanation.page_count,
                    image_payload=image_payload,
                    ocr_text=ocr_text,
                )
                annotation_result = self._coerce_annotation_result(
                    payload.get("annotation_result"),
                    page=page_no,
                    file_index=file_index,
                )
                page_explanations.append(
                    DrawingPageExplanation(
                        page=page_no,
                        page_asset=page_asset,
                        view_explanations=[
                            DrawingViewExplanation(
                                view_index=1,
                                label="整页",
                                region={"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0, "unit": "ratio"},
                                visual_summary=str(payload.get("visual_summary") or f"第 {page_no} 页图解"),
                                detected_features=[str(item) for item in payload.get("detected_features", []) if item],
                                related_operations=[str(item) for item in payload.get("related_operations", []) if item],
                                risk_notes=[str(item) for item in payload.get("risk_notes", []) if item],
                            )
                        ],
                        visual_summary=str(payload.get("visual_summary") or f"第 {page_no} 页图解"),
                        detected_features=[str(item) for item in payload.get("detected_features", []) if item],
                        related_operations=[str(item) for item in payload.get("related_operations", []) if item]
                        or [f"第 {file_index} 份图纸-第 {page_no} 页"],
                        risk_notes=[str(item) for item in payload.get("risk_notes", []) if item],
                        annotation_result=annotation_result,
                    )
                )
                continue

            view_explanations: list[DrawingViewExplanation] = []
            view_annotation_results = []
            summaries: list[str] = []
            features: list[str] = []
            operations: list[str] = []
            risks: list[str] = []
            for region in view_regions:
                view_payload = crop_view_payload(image_path, region, page=page_no)
                payload = await ai_service.explain_single_drawing_page(
                    file_name=path.name,
                    file_index=file_index,
                    page=page_no,
                    page_count=explanation.page_count,
                    image_payload=view_payload,
                    ocr_text=ocr_text,
                    view_label=region.label,
                    view_region={
                        "x": region.x,
                        "y": region.y,
                        "width": region.width,
                        "height": region.height,
                    },
                )
                view_annotation = self._coerce_annotation_result(
                    payload.get("annotation_result"),
                    page=page_no,
                    file_index=file_index,
                )
                view_annotation = map_view_local_regions_to_page(
                    view_annotation,
                    view_x=region.x,
                    view_y=region.y,
                    view_width=region.width,
                    view_height=region.height,
                )
                view_annotation_results.append(view_annotation)
                summary = str(payload.get("visual_summary") or region.label)
                summaries.append(f"{region.label}：{summary}")
                view_explanations.append(
                    DrawingViewExplanation(
                        view_index=region.view_index,
                        label=region.label,
                        region={**region.as_dict(), "unit": "ratio"},
                        visual_summary=summary,
                        detected_features=[str(item) for item in payload.get("detected_features", []) if item],
                        related_operations=[str(item) for item in payload.get("related_operations", []) if item],
                        risk_notes=[str(item) for item in payload.get("risk_notes", []) if item],
                    )
                )
                features.extend(str(item) for item in payload.get("detected_features", []) if item)
                operations.extend(str(item) for item in payload.get("related_operations", []) if item)
                risks.extend(str(item) for item in payload.get("risk_notes", []) if item)

            page_explanations.append(
                DrawingPageExplanation(
                    page=page_no,
                    page_asset=page_asset,
                    view_explanations=view_explanations,
                    visual_summary="；".join(summaries),
                    detected_features=list(dict.fromkeys(features)),
                    related_operations=list(dict.fromkeys(operations)) or [f"第 {file_index} 份图纸-第 {page_no} 页"],
                    risk_notes=list(dict.fromkeys(risks)),
                    annotation_result=merge_annotation_results(view_annotation_results),
                )
            )

        explanation.page_explanations = page_explanations
        if path.suffix.lower() == ".pdf":
            total_pages = self._count_pdf_pages(path)
            if total_pages > len(page_explanations):
                explanation.risk_notes.append(
                    f"PDF 共 {total_pages} 页，当前图解覆盖前 {len(page_explanations)} 页（上限 {settings.agent_max_pdf_pages}）"
                )
        explanation.page_index = page_explanations[0].page
        explanation.page_asset = page_explanations[0].page_asset
        explanation.visual_summary = "；".join(item.visual_summary for item in page_explanations if item.visual_summary)
        explanation.detected_features = list(dict.fromkeys(feature for item in page_explanations for feature in item.detected_features))
        explanation.related_operations = list(
            dict.fromkeys(op for item in page_explanations for op in item.related_operations)
        )
        explanation.risk_notes = list(dict.fromkeys(note for item in page_explanations for note in item.risk_notes))
        explanation.annotation_result = merge_annotation_results([item.annotation_result for item in page_explanations])
        return explanation

    def _coerce_annotation_result(self, value: Any, *, page: int, file_index: int) -> DrawingAnnotationResult:
        if not isinstance(value, dict):
            return DrawingAnnotationResult()
        annotations = value.get("annotations") if isinstance(value.get("annotations"), list) else []
        export_rows = value.get("export_rows") if isinstance(value.get("export_rows"), list) else []

        safe_annotations: list[DrawingAnnotation] = []
        for index, item in enumerate(annotations, start=1):
            if not isinstance(item, dict):
                continue
            candidate = dict(item)
            candidate.setdefault("annotation_id", f"F{file_index:02d}P{page:02d}A{index:03d}")
            candidate.setdefault("raw_text", candidate.get("normalized_text") or candidate.get("parameter_name") or candidate["annotation_id"])
            try:
                safe_annotations.append(DrawingAnnotation.model_validate(candidate))
            except ValidationError:
                continue

        safe_rows: list[AnnotationExportRow] = []
        for index, item in enumerate(export_rows, start=1):
            if not isinstance(item, dict):
                continue
            candidate = dict(item)
            candidate.setdefault("row_no", index)
            candidate.setdefault("annotation_id", f"F{file_index:02d}P{page:02d}A{index:03d}")
            candidate.setdefault("parameter_name", candidate.get("raw_text") or candidate.get("annotation_id") or "未命名参数")
            try:
                safe_rows.append(AnnotationExportRow.model_validate(candidate))
            except ValidationError:
                continue

        if not safe_rows:
            safe_rows = [
                AnnotationExportRow(
                    row_no=index,
                    annotation_id=annotation.annotation_id,
                    parameter_name=annotation.parameter_name or annotation.normalized_text or annotation.raw_text or annotation.annotation_id,
                    parameter_value=annotation.parameter_value or "",
                    upper_limit=annotation.upper_limit or "",
                    lower_limit=annotation.lower_limit or "",
                    unit=annotation.unit or "",
                    semantic_type=annotation.semantic_type,
                    review_status=annotation.review_status,
                    source=annotation.source,
                    confidence=annotation.confidence,
                )
                for index, annotation in enumerate(safe_annotations, start=1)
            ]

        return normalize_annotation_result(
            DrawingAnnotationResult(
                annotations=safe_annotations,
                export_rows=safe_rows,
                bubble_diagram_available=False,
                review_required_count=sum(
                    1 for item in safe_annotations if item.review_status in {"pending", "needs_manual_review"}
                ),
            ),
            page=page,
            file_index=file_index,
        )


drawing_explanation_service = DrawingExplanationService()