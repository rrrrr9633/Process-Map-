from app.models.annotation import BoundingBox, DrawingAnnotation, DrawingAnnotationResult
from app.models.case import ProcessCase
from app.models.drawing import DrawingParseResult
from app.models.drawing_explanation import BubbleDiagramAsset, DrawingExplanation, DrawingPageAsset, DrawingPageExplanation
from app.models.process import Operation, OperationType, ProcessMode, ProcessPlan
from app.services.final_guidance_service import final_guidance_service


def test_final_guidance_links_process_annotations_and_bubble_images() -> None:
    case = ProcessCase(
        case_id="case_1",
        case_name="曲轴样件",
        drawing_parse_result=DrawingParseResult(),
        process_plan=ProcessPlan(
            mode=ProcessMode.STANDARD_8,
            title="曲轴工序",
            operations=[
                Operation(
                    operation_no="OP10",
                    operation_name="轴颈精磨",
                    operation_type=OperationType.FINISHING,
                    content="精磨主轴颈并控制粗糙度",
                    worker_steps=["装夹找正", "精磨轴颈"],
                    quality_gates=["Ra1.6 达标"],
                    drawing_basis=["主轴颈粗糙度标注"],
                )
            ],
        ),
    )
    annotation = DrawingAnnotation(
        annotation_id="F01P01A001",
        label="001",
        region=BoundingBox(page=1, x=0.1, y=0.1, width=0.1, height=0.1),
        raw_text="▽ Ra1.6",
        parameter_name="主轴颈粗糙度",
        parameter_value="▽ Ra1.6",
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
                page_asset=DrawingPageAsset(
                    file_index=1,
                    file_name="drawing.pdf",
                    page=1,
                    image_path="/tmp/page.png",
                    image_url="pages/page.png",
                ),
                visual_summary="主轴颈精加工标注",
                annotation_result=DrawingAnnotationResult(annotations=[annotation]),
                bubble_asset=BubbleDiagramAsset(
                    file_index=1,
                    file_name="drawing.pdf",
                    page=1,
                    image_url="bubbles/bubble.png",
                    status="generated",
                ),
            )
        ],
    )

    guidance = final_guidance_service.build(
        case=case,
        job_id="job_1",
        explanations=[explanation],
        export_csv_url="exports/annotations.csv",
    )

    assert guidance["status"] == "ready_for_process_review"
    assert guidance["image_refs"][0]["image_url"] == "bubbles/bubble.png"
    assert guidance["operation_units"][0]["operation_no"] == "OP10"
    assert "Ra1.6" in guidance["usable_annotations"][0]
