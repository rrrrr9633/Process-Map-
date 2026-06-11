from __future__ import annotations

from uuid import uuid4

from app.models.annotation import DrawingAnnotation
from app.models.case import ProcessCase
from app.models.drawing_explanation import DrawingExplanation
from app.models.process import Operation, OperationType
from app.models.process_drawing import (
    ProcessDrawingCallout,
    ProcessDrawingPlan,
    ProcessDrawingSheet,
    ProcessDrawingView,
)
from app.services.engineering_text import normalize_engineering_text


class ProcessDrawingPlanService:
    """Build a deterministic process drawing draft plan from case data."""

    def build(
        self,
        *,
        case: ProcessCase,
        job_id: str = "",
        explanations: list[DrawingExplanation] | None = None,
        final_guidance: dict | None = None,
    ) -> ProcessDrawingPlan:
        operations = case.process_plan.operations or []
        annotations = self._collect_annotations(explanations or [])
        plan = ProcessDrawingPlan(
            plan_id=uuid4().hex,
            case_id=case.case_id,
            job_id=job_id or str(final_guidance.get("job_id", "") if final_guidance else ""),
            part_name=case.drawing_parse_result.part.part_name or case.case_name,
            drawing_no=case.drawing_parse_result.part.drawing_no or "",
            title=f"{case.case_name} 细分工艺图草稿",
            source_operation_nos=[operation.operation_no for operation in operations],
            source_annotation_ids=[annotation.annotation_id for annotation in annotations],
            sheets=self._build_default_sheets(operations, annotations),
            assumptions=[
                "当前阶段生成的是工艺图草稿计划，不代表生产级 CAD 图纸。",
                "曲轴轮廓、加工状态和标注位置由后续确定性绘图服务按模板渲染。",
                "所有低置信或待复核标注不得直接进入投产工艺卡。",
            ],
            risks=self._risk_lines(case, annotations),
            handoff=[
                "先由工艺人员确认三张工艺图分组是否符合实际路线。",
                "确认 accepted 标注与对应工序绑定后，再进入 SVG/PNG/DXF 渲染。",
                "DXF 导出只能读取本计划层，不允许由大模型直接生成 CAD 实体。",
            ],
            requires_manual_review=True,
        )
        return plan

    def _build_default_sheets(
        self,
        operations: list[Operation],
        annotations: list[DrawingAnnotation],
    ) -> list[ProcessDrawingSheet]:
        groups = [
            {
                "sheet_no": "S01",
                "title": "毛坯/粗加工状态图",
                "stage": "blank_rough",
                "operation_types": {
                    OperationType.BLANK_PREPARATION,
                    OperationType.BASELINE_PROCESSING,
                    OperationType.ROUGH_MACHINING,
                },
                "view_type": "crankshaft_side_outline",
                "summary": "表达毛坯确认、基准建立和粗加工余量控制。",
                "features": ["曲轴毛坯", "两端面", "中心孔", "主轴颈", "连杆颈", "平衡块"],
            },
            {
                "sheet_no": "S02",
                "title": "半精加工状态图",
                "stage": "semi_finish",
                "operation_types": {
                    OperationType.SEMI_FINISHING,
                    OperationType.HOLE_PROCESSING,
                },
                "view_type": "crankshaft_process_state",
                "summary": "表达半精车、圆角保护、法兰孔系和油道加工控制。",
                "features": ["轴颈", "圆角", "法兰端", "螺栓孔", "定位销孔", "油道"],
            },
            {
                "sheet_no": "S03",
                "title": "精加工/终检状态图",
                "stage": "finish_inspection",
                "operation_types": {
                    OperationType.FINISHING,
                    OperationType.INSPECTION,
                    OperationType.SPECIAL_PROCESS,
                    OperationType.CLEANING_FINAL_INSPECTION,
                },
                "view_type": "crankshaft_final_inspection",
                "summary": "表达精磨滚压、探伤动平衡、清洁度和成品终检要求。",
                "features": ["主轴颈", "连杆颈", "滚压区域", "打刻区", "探伤区域", "油道", "整件"],
            },
        ]

        sheets: list[ProcessDrawingSheet] = []
        assigned_operation_nos: set[str] = set()
        for group in groups:
            group_operations = [
                operation
                for operation in operations
                if operation.operation_type in group["operation_types"]
            ]
            assigned_operation_nos.update(operation.operation_no for operation in group_operations)
            sheet_annotations = self._match_annotations(group_operations, annotations)
            sheet_callouts = self._operation_callouts(group["sheet_no"], group_operations)
            sheet_callouts.extend(self._annotation_callouts(group["sheet_no"], sheet_annotations))
            operation_nos = [operation.operation_no for operation in group_operations]
            annotation_ids = [annotation.annotation_id for annotation in sheet_annotations]
            sheets.append(
                ProcessDrawingSheet(
                    sheet_no=str(group["sheet_no"]),
                    title=str(group["title"]),
                    stage=group["stage"],
                    related_operation_nos=operation_nos,
                    summary=str(group["summary"]),
                    views=[
                        ProcessDrawingView(
                            view_id=f"{group['sheet_no']}-V01",
                            title=str(group["title"]),
                            view_type=group["view_type"],
                            source="template",
                            highlight_features=list(group["features"]),
                            operation_nos=operation_nos,
                            annotation_ids=annotation_ids,
                            notes=self._view_notes(group_operations, sheet_annotations),
                            geometry={"template": "crankshaft_process_draft", "stage": group["stage"]},
                            callouts=sheet_callouts,
                        )
                    ],
                    callouts=sheet_callouts,
                    notes=self._sheet_notes(group_operations, sheet_annotations),
                    requires_manual_review=True,
                    review_reason="工艺图草稿需确认工序分组、加工余量、标注绑定和企业制图规范。",
                )
            )

        remaining_operations = [operation for operation in operations if operation.operation_no not in assigned_operation_nos]
        if remaining_operations:
            sheets[-1].related_operation_nos.extend(operation.operation_no for operation in remaining_operations)
            sheets[-1].notes.append(
                "以下工序暂归入终检状态图复核："
                + "、".join(f"{operation.operation_no} {operation.operation_name}" for operation in remaining_operations)
            )
        return sheets

    def _collect_annotations(self, explanations: list[DrawingExplanation]) -> list[DrawingAnnotation]:
        annotations: list[DrawingAnnotation] = []
        for explanation in explanations:
            if explanation.page_explanations:
                for page in explanation.page_explanations:
                    annotations.extend(page.annotation_result.annotations)
            else:
                annotations.extend(explanation.annotation_result.annotations)
        return annotations

    def _match_annotations(
        self,
        operations: list[Operation],
        annotations: list[DrawingAnnotation],
    ) -> list[DrawingAnnotation]:
        if not operations or not annotations:
            return []
        operation_text = " ".join(
            normalize_engineering_text(
                " ".join(
                    [
                        operation.operation_name,
                        operation.content,
                        " ".join(operation.targets),
                        " ".join(operation.control_points),
                        " ".join(operation.inspection_items),
                        " ".join(operation.drawing_basis),
                    ]
                )
            )
            for operation in operations
        )
        matched: list[DrawingAnnotation] = []
        for annotation in annotations:
            annotation_text = normalize_engineering_text(
                " ".join(
                    item
                    for item in [
                        annotation.label or "",
                        annotation.parameter_name or "",
                        annotation.parameter_value or "",
                        annotation.normalized_text or "",
                        annotation.raw_text or "",
                        annotation.semantic_type,
                    ]
                    if item
                )
            )
            if self._annotation_matches_operations(annotation, annotation_text, operation_text):
                matched.append(annotation)
            if len(matched) >= 8:
                break
        return matched

    def _annotation_matches_operations(
        self,
        annotation: DrawingAnnotation,
        annotation_text: str,
        operation_text: str,
    ) -> bool:
        if annotation.semantic_type in {"roughness", "geometric_tolerance", "tolerance"} and any(
            keyword in operation_text for keyword in ("精磨", "滚压", "终检", "检测")
        ):
            return True
        if annotation.semantic_type in {"inspection_note", "quality_note"} and any(
            keyword in operation_text for keyword in ("检测", "探伤", "动平衡", "清洗", "终检")
        ):
            return True
        if annotation.semantic_type == "process_note" and any(
            keyword in operation_text for keyword in ("加工", "滚压", "去毛刺", "打刻")
        ):
            return True
        keywords = ["主轴颈", "连杆颈", "圆角", "油道", "法兰", "中心孔", "清洁度", "动平衡", "探伤", "材料"]
        return any(keyword in annotation_text and keyword in operation_text for keyword in keywords)

    def _operation_callouts(self, sheet_no: str, operations: list[Operation]) -> list[ProcessDrawingCallout]:
        callouts: list[ProcessDrawingCallout] = []
        for index, operation in enumerate(operations[:6], start=1):
            callouts.append(
                ProcessDrawingCallout(
                    callout_id=f"{sheet_no}-OP{index:02d}",
                    label=operation.operation_no,
                    text=normalize_engineering_text(operation.operation_name),
                    target="、".join(operation.targets[:3]),
                    target_feature=operation.targets[0] if operation.targets else "",
                    related_operation_nos=[operation.operation_no],
                    position={"slot": index, "zone": "operation"},
                    requires_manual_review=operation.requires_manual_review,
                    review_reason="该工序需要人工复核" if operation.requires_manual_review else "",
                )
            )
        return callouts

    def _annotation_callouts(
        self,
        sheet_no: str,
        annotations: list[DrawingAnnotation],
    ) -> list[ProcessDrawingCallout]:
        callouts: list[ProcessDrawingCallout] = []
        for index, annotation in enumerate(annotations[:6], start=1):
            label = annotation.label or annotation.parameter_name or annotation.annotation_id
            text = annotation.parameter_value or annotation.normalized_text or annotation.raw_text or "待确认"
            needs_review = (
                annotation.review_status != "accepted"
                or annotation.confidence < 0.85
                or annotation.source == "agent_reasoning"
            )
            callouts.append(
                ProcessDrawingCallout(
                    callout_id=f"{sheet_no}-AN{index:02d}",
                    label=normalize_engineering_text(label)[:12],
                    text=normalize_engineering_text(text),
                    target=annotation.parameter_name or annotation.label or "图纸标注",
                    target_feature=annotation.parameter_name or annotation.label or "",
                    related_annotation_ids=[annotation.annotation_id],
                    position={
                        "slot": index,
                        "zone": "annotation",
                        "source_x": annotation.region.x,
                        "source_y": annotation.region.y,
                        "source_unit": annotation.region.unit,
                    },
                    requires_manual_review=needs_review,
                    review_reason=annotation.review_reason or ("标注未达到自动放行条件" if needs_review else ""),
                )
            )
        return callouts

    def _view_notes(
        self,
        operations: list[Operation],
        annotations: list[DrawingAnnotation],
    ) -> list[str]:
        notes = []
        if operations:
            notes.append("关联工序：" + "、".join(f"{item.operation_no} {item.operation_name}" for item in operations[:4]))
        if annotations:
            notes.append(f"关联精细标注 {len(annotations)} 条，渲染前需确认标注绑定。")
        return notes

    def _sheet_notes(
        self,
        operations: list[Operation],
        annotations: list[DrawingAnnotation],
    ) -> list[str]:
        notes: list[str] = []
        for operation in operations[:4]:
            if operation.control_points:
                notes.append(f"{operation.operation_no} 控制点：{normalize_engineering_text(operation.control_points[0])}")
        review_count = sum(
            1
            for annotation in annotations
            if annotation.review_status != "accepted" or annotation.confidence < 0.85
        )
        if review_count:
            notes.append(f"{review_count} 条标注需要人工复核后才能进入正式工艺图。")
        if not notes:
            notes.append("当前页为模板草稿，需补充企业图框、比例和加工余量规则。")
        return notes

    def _risk_lines(self, case: ProcessCase, annotations: list[DrawingAnnotation]) -> list[str]:
        risks = [flag.message for flag in case.drawing_parse_result.risk_flags]
        review_count = sum(
            1
            for annotation in annotations
            if annotation.review_status != "accepted" or annotation.confidence < 0.85
        )
        if review_count:
            risks.append(f"存在 {review_count} 条精细标注未达到自动放行条件。")
        if case.process_plan.requires_manual_review:
            risks.append("当前工序方案已标记为需要人工复核。")
        return list(dict.fromkeys(item for item in risks if item))


process_drawing_plan_service = ProcessDrawingPlanService()