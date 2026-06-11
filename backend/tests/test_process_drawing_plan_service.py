from app.models.annotation import BoundingBox, DrawingAnnotation, DrawingAnnotationResult
from app.models.case import ProcessCase
from app.models.drawing import DrawingParseResult, PartInfo
from app.models.drawing_explanation import DrawingExplanation, DrawingPageExplanation
from app.models.process import Operation, OperationType, ProcessMode, ProcessPlan
from app.services.process_drawing_plan_service import process_drawing_plan_service


def test_process_drawing_plan_service_builds_three_default_sheets() -> None:
    case = ProcessCase(
        case_id="case_1",
        case_name="曲轴1000329-03",
        drawing_parse_result=DrawingParseResult(
            part=PartInfo(part_name="曲轴", drawing_no="1000329-03"),
        ),
        process_plan=ProcessPlan(
            mode=ProcessMode.DETAILED_10,
            title="曲轴工序",
            operations=[
                Operation(
                    operation_no="01",
                    operation_name="毛坯修整",
                    operation_type=OperationType.BLANK_PREPARATION,
                    targets=["曲轴毛坯"],
                    content="修整毛坯飞边和表面缺陷",
                    control_points=["确认毛坯质量"],
                ),
                Operation(
                    operation_no="05",
                    operation_name="半精车精修",
                    operation_type=OperationType.SEMI_FINISHING,
                    targets=["轴颈", "圆角"],
                    content="半精车轴颈、台阶和圆角",
                    control_points=["保护圆角"],
                ),
                Operation(
                    operation_no="07",
                    operation_name="轴颈精磨滚压",
                    operation_type=OperationType.FINISHING,
                    targets=["主轴颈", "连杆颈"],
                    content="对轴颈进行精磨和滚压",
                    control_points=["控制粗糙度"],
                ),
            ],
        ),
    )
    annotation = DrawingAnnotation(
        annotation_id="A001",
        label="粗糙度",
        region=BoundingBox(page=1, x=0.2, y=0.3, width=0.02, height=0.02),
        raw_text="Ra1.6",
        parameter_name="主轴颈粗糙度",
        parameter_value="Ra1.6",
        semantic_type="roughness",
        source="pdf_page_image",
        confidence=0.92,
        review_status="accepted",
    )
    explanation = DrawingExplanation(
        file_index=1,
        file_name="drawing.pdf",
        source_path="/tmp/drawing.pdf",
        page_explanations=[
            DrawingPageExplanation(
                page=1,
                annotation_result=DrawingAnnotationResult(annotations=[annotation]),
            )
        ],
    )

    plan = process_drawing_plan_service.build(
        case=case,
        job_id="job_1",
        explanations=[explanation],
    )

    assert plan.case_id == "case_1"
    assert plan.job_id == "job_1"
    assert plan.part_name == "曲轴"
    assert plan.drawing_no == "1000329-03"
    assert len(plan.sheets) == 3
    assert [sheet.sheet_no for sheet in plan.sheets] == ["S01", "S02", "S03"]
    assert plan.sheets[0].related_operation_nos == ["01"]
    assert plan.sheets[1].related_operation_nos == ["05"]
    assert plan.sheets[2].related_operation_nos == ["07"]
    assert "A001" in plan.source_annotation_ids
    assert plan.sheets[2].views[0].annotation_ids == ["A001"]
    assert plan.sheets[2].callouts[-1].related_annotation_ids == ["A001"]