from __future__ import annotations

from typing import Any

from app.models.annotation import DrawingAnnotation
from app.models.case import ProcessCase
from app.models.drawing_explanation import DrawingExplanation
from app.services.engineering_text import normalize_engineering_text


class FinalGuidanceService:
    """Build the final human-readable instruction unit after fine annotation."""

    def build(
        self,
        *,
        case: ProcessCase,
        job_id: str,
        explanations: list[DrawingExplanation],
        export_csv_url: str,
    ) -> dict[str, Any]:
        annotations = self._collect_annotations(explanations)
        usable = [
            item
            for item in annotations
            if item.confidence >= 0.85 and item.review_status == "accepted" and item.source != "agent_reasoning"
        ]
        review = [
            item
            for item in annotations
            if item.review_status in {"pending", "needs_manual_review"}
            or item.confidence < 0.85
            or item.source == "agent_reasoning"
        ]
        image_refs = self._image_refs(explanations)
        operation_units = self._operation_units(case, usable, review)

        return {
            "case_id": case.case_id,
            "case_name": case.case_name,
            "job_id": job_id,
            "title": f"{case.case_name} 最终工序流程指导",
            "objective": "把 3D/工程图输入、快速工序、精细标注 CSV 和气泡图合并成工人/工艺员能直接审核的指导单元。",
            "status": self._status(len(annotations), len(review), len(image_refs)),
            "summary": self._summary(case, annotations, usable, review, image_refs),
            "csv_url": export_csv_url,
            "image_refs": image_refs,
            "operation_units": operation_units,
            "usable_annotations": [self._annotation_line(item) for item in usable[:12]],
            "review_required": [self._annotation_line(item) for item in review[:16]],
            "handoff": [
                "先看最终指导单元确认总体流程，再打开气泡图核对标注位置。",
                "CSV 作为机器可追溯数据源，优先阅读 readable_summary、risk_level、review_action 三列。",
                "所有 review_required 项确认前，不允许把对应尺寸/公差直接写入投产工艺卡。",
            ],
        }

    def _collect_annotations(self, explanations: list[DrawingExplanation]) -> list[DrawingAnnotation]:
        annotations: list[DrawingAnnotation] = []
        for explanation in explanations:
            page_sources = explanation.page_explanations or []
            if page_sources:
                for page in page_sources:
                    annotations.extend(page.annotation_result.annotations)
            else:
                annotations.extend(explanation.annotation_result.annotations)
        return annotations

    def _image_refs(self, explanations: list[DrawingExplanation]) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for explanation in explanations:
            pages = explanation.page_explanations or []
            for page in pages:
                bubble = page.bubble_asset or explanation.bubble_asset
                if not bubble or not bubble.image_url:
                    continue
                refs.append(
                    {
                        "file_index": explanation.file_index,
                        "file_name": explanation.file_name,
                        "page": page.page,
                        "title": f"{explanation.file_name} 第 {page.page} 页气泡图",
                        "image_url": bubble.image_url,
                        "summary": page.visual_summary or explanation.visual_summary,
                    }
                )
        return refs

    def _operation_units(
        self,
        case: ProcessCase,
        usable: list[DrawingAnnotation],
        review: list[DrawingAnnotation],
    ) -> list[dict[str, Any]]:
        usable_text = [self._annotation_line(item) for item in usable[:8]]
        review_text = [self._annotation_line(item) for item in review[:8]]
        units: list[dict[str, Any]] = []
        for operation in case.process_plan.operations:
            units.append(
                {
                    "operation_no": operation.operation_no,
                    "operation_name": operation.operation_name,
                    "instruction": normalize_engineering_text(operation.content),
                    "worker_steps": [normalize_engineering_text(item) for item in operation.worker_steps[:4]],
                    "quality_gates": [normalize_engineering_text(item) for item in operation.quality_gates[:4]],
                    "drawing_basis": [normalize_engineering_text(item) for item in operation.drawing_basis[:4]],
                    "usable_annotation_basis": usable_text[:4],
                    "review_before_release": review_text[:4],
                }
            )
        return units

    def _annotation_line(self, annotation: DrawingAnnotation) -> str:
        name = normalize_engineering_text(annotation.parameter_name or annotation.label or annotation.annotation_id)
        value = normalize_engineering_text(annotation.parameter_value or annotation.normalized_text or annotation.raw_text or "待确认")
        source = "图像识别" if annotation.source == "pdf_page_image" else "PDF文本" if annotation.source == "pdf_text" else "模型推理"
        return f"{name} = {value}；来源：{source}；置信度：{annotation.confidence:.2f}；状态：{annotation.review_status}"

    def _status(self, annotation_count: int, review_count: int, image_count: int) -> str:
        if annotation_count == 0 or image_count == 0:
            return "needs_annotation"
        if review_count:
            return "review_required"
        return "ready_for_process_review"

    def _summary(
        self,
        case: ProcessCase,
        annotations: list[DrawingAnnotation],
        usable: list[DrawingAnnotation],
        review: list[DrawingAnnotation],
        image_refs: list[dict[str, Any]],
    ) -> str:
        return (
            f"已形成 {len(case.process_plan.operations)} 道工序指导、{len(image_refs)} 张气泡图、"
            f"{len(annotations)} 条精细标注。其中 {len(usable)} 条可优先作为工艺依据，"
            f"{len(review)} 条需要人工复核后才能进入正式工艺卡。"
        )


final_guidance_service = FinalGuidanceService()
