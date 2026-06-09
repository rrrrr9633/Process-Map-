import asyncio
import hashlib
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.models.drawing import DrawingParseResult
from app.models.drawing_explanation import AnnotationUpdateRequest, DrawingExplanation, ProcessJob
from app.models.process import ProcessMode, ProcessPlan
from app.schemas.process import EditedPlanRequest, GenerateFromParseRequest, GenerateFromTextRequest, ProcessGenerationResponse
from app.services.ai_service import AIServiceError, ai_service
from app.services.bubble_diagram_service import bubble_diagram_service
from app.services.case_service import case_service
from app.services.drawing_explanation_service import drawing_explanation_service
from app.services.annotation_normalizer import (
    convert_annotation_region_to_ratio,
    merge_annotation_results,
    normalize_annotation,
    rebuild_export_rows,
)
from app.services.drawing_parser import DrawingParser
from app.services.export_service import ExportService
from app.services.flow_builder import FlowBuilder
from app.services.job_service import job_service
from app.services.process_agent import process_agent
from app.services.process_generator import ProcessGenerator

router = APIRouter(prefix="/process", tags=["process"])
parser = DrawingParser()
generator = ProcessGenerator()
flow_builder = FlowBuilder()
export_service = ExportService()


class ArchiveResponse(BaseModel):
    path: str
    markdown: str


SUPPORTED_UPLOAD_SUFFIXES = {"pdf", "png", "jpg", "jpeg", "webp", "bmp", "dwg", "dxf"}


def _upload_suffix(file: UploadFile) -> str:
    return file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else "bin"


def _find_existing_upload(upload_dir: Path, suffix: str, content: bytes) -> Path | None:
    digest = hashlib.sha256(content).hexdigest()
    for candidate in upload_dir.glob(f"*.{suffix}"):
        if not candidate.is_file() or candidate.stat().st_size != len(content):
            continue
        try:
            if hashlib.sha256(candidate.read_bytes()).hexdigest() == digest:
                return candidate
        except OSError:
            continue
    return None


async def _store_upload(file: UploadFile, upload_dir: Path) -> Path:
    suffix = _upload_suffix(file)
    if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"暂不支持的文件格式：{suffix}")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail=f"上传文件为空：{file.filename or '未命名文件'}")

    existing_path = _find_existing_upload(upload_dir, suffix, content)
    if existing_path:
        print(f"[process] reuse uploaded file: {existing_path.name} <- {file.filename or 'unnamed'}", flush=True)
        return existing_path

    temp_path = upload_dir / f"{uuid4().hex}.{suffix}"
    with open(temp_path, "wb") as target:
        target.write(content)
    print(f"[process] stored uploaded file: {temp_path.name} <- {file.filename or 'unnamed'}", flush=True)
    return temp_path


async def _apply_ai_enhancement(
    process_plan: ProcessPlan,
    parse_result: DrawingParseResult,
    enabled: bool,
) -> tuple[ProcessPlan, list[str]]:
    if not enabled:
        return process_plan, []

    try:
        return await ai_service.enhance_process_plan(process_plan, parse_result.model_dump(mode="json"))
    except AIServiceError as exc:
        process_plan.requires_manual_review = True
        return process_plan, [str(exc)]
    except Exception:
        process_plan.requires_manual_review = True
        return process_plan, ["AI 增强暂时不可用，请稍后重试"]




async def _run_sync_explanation_pipeline(
    file_paths: list[str],
    mode: ProcessMode,
) -> tuple[str, list[DrawingExplanation], ProcessGenerationResponse]:
    """同步接口：逐份逐页图解 + 气泡图 + 合并工艺流程（与 Job 批量主链一致）。"""
    job = job_service.create_job(file_paths)
    job_id = job.job_id
    explanations: list[DrawingExplanation] = []
    for index, file_path in enumerate(file_paths, start=1):
        explanation = await drawing_explanation_service.explain_file(
            file_path,
            job_service.pages_dir(job_id),
            index,
        )
        explanation = bubble_diagram_service.generate(explanation, job_service.bubbles_dir(job_id))
        explanations.append(explanation)
    csv_path, _ = export_service.export_annotations(explanations, job_service.exports_dir(job_id))
    for explanation in explanations:
        for page_explanation in explanation.page_explanations:
            if page_explanation.bubble_asset:
                page_explanation.bubble_asset.export_csv_path = str(csv_path)
                page_explanation.bubble_asset.export_csv_url = f"exports/{csv_path.name}"
        if explanation.bubble_asset:
            explanation.bubble_asset.export_csv_path = str(csv_path)
            explanation.bubble_asset.export_csv_url = f"exports/{csv_path.name}"
    job_service.set_explanations(job_id, explanations)

    agent_response = await process_agent.run_from_files(file_paths, mode, explanations=explanations)
    result = ProcessGenerationResponse(
        parse_result=agent_response.parse_result,
        annotation_result=agent_response.annotation_result,
        process_plan=agent_response.process_plan,
        flow=agent_response.flow,
        similar_cases=agent_response.similar_cases,
        ai_suggestions=agent_response.ai_suggestions,
        agent_trace=agent_response.agent_trace,
        job_id=job_id,
        explanations=explanations,
    )
    job_service.set_process_result(job_id, result.model_dump(mode="json"))
    job_service.complete(job_id)
    return job_id, explanations, result

async def _explain_process_job_file(job_id: str, file_path: str, file_index: int) -> DrawingExplanation:
    return await drawing_explanation_service.explain_file(
        file_path,
        job_service.pages_dir(job_id),
        file_index,
    )


async def _run_process_job(job_id: str, file_paths: list[str], mode: ProcessMode) -> None:
    try:
        total = max(1, len(file_paths))
        job_service.update(job_id, stage="rendering", status="running", progress=5, message=f"开始渲染并识别 {total} 份图纸")

        tasks = [
            asyncio.create_task(_explain_process_job_file(job_id, file_path, index))
            for index, file_path in enumerate(file_paths, start=1)
        ]
        pending = set(tasks)
        explanations_by_index: dict[int, DrawingExplanation] = {}
        completed = 0

        job_service.update(
            job_id,
            stage="explaining",
            status="running",
            progress=10,
            message=f"已同时启动 {total} 份图纸识别，等待 AI 返回",
        )

        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                explanation = task.result()
                explanations_by_index[explanation.file_index] = explanation
                completed += 1
                explanations = [explanations_by_index[index] for index in sorted(explanations_by_index)]
                job_service.set_explanations(job_id, explanations)
                job_service.update(
                    job_id,
                    stage="explaining",
                    status="running",
                    progress=10 + int(completed / total * 45),
                    message=f"已完成 {completed}/{total} 份图纸识别",
                )

        explanations = [explanations_by_index[index] for index in sorted(explanations_by_index)]
        if len(explanations) != len(file_paths):
            raise RuntimeError(f"图纸识别数量不一致：期望 {len(file_paths)}，实际 {len(explanations)}")

        job_service.update(job_id, stage="bubble_generating", status="running", progress=60, message="正在生成气泡图")
        explanations = [
            bubble_diagram_service.generate(explanation, job_service.bubbles_dir(job_id))
            for explanation in explanations
        ]
        csv_path, json_path = export_service.export_annotations(explanations, job_service.exports_dir(job_id))
        for explanation in explanations:
            for page_explanation in explanation.page_explanations:
                if page_explanation.bubble_asset:
                    page_explanation.bubble_asset.export_csv_path = str(csv_path)
                    page_explanation.bubble_asset.export_csv_url = f"exports/{csv_path.name}"
            if explanation.bubble_asset:
                explanation.bubble_asset.export_csv_path = str(csv_path)
                explanation.bubble_asset.export_csv_url = f"exports/{csv_path.name}"
        job_service.set_explanations(job_id, explanations)

        job_service.update(job_id, stage="flow_generating", status="running", progress=75, message=f"正在基于 {total} 份图纸汇总生成工艺流程")
        agent_response = await process_agent.run_from_files(file_paths, mode, explanations=explanations)
        result = ProcessGenerationResponse(
            parse_result=agent_response.parse_result,
            annotation_result=agent_response.annotation_result,
            process_plan=agent_response.process_plan,
            flow=agent_response.flow,
            similar_cases=agent_response.similar_cases,
            ai_suggestions=agent_response.ai_suggestions,
            agent_trace=agent_response.agent_trace,
        )
        job_service.set_process_result(job_id, result.model_dump(mode="json"))
        job_service.complete(job_id)
    except Exception as exc:
        for task in locals().get("pending", set()):
            task.cancel()
        job_service.fail(job_id, f"{type(exc).__name__}: {exc}")


@router.post("/jobs/upload-batch", response_model=ProcessJob)
async def upload_batch_job(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    mode: ProcessMode = ProcessMode.STANDARD_8,
) -> ProcessJob:
    if not files:
        raise HTTPException(status_code=400, detail="请至少上传 1 个图纸文件")

    upload_dir = Path("./uploads")
    upload_dir.mkdir(exist_ok=True, parents=True)
    temp_paths = [await _store_upload(file, upload_dir) for file in files]
    job = job_service.create_job([str(path) for path in temp_paths])
    background_tasks.add_task(_run_process_job, job.job_id, [str(path) for path in temp_paths], mode)
    return job


@router.get("/jobs/{job_id}", response_model=ProcessJob)
def get_process_job(job_id: str) -> ProcessJob:
    try:
        return job_service.get(job_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="任务不存在")


@router.get("/jobs/{job_id}/assets/{asset_path:path}")
def get_process_job_asset(job_id: str, asset_path: str) -> FileResponse:
    try:
        path = job_service.resolve_asset(job_id, asset_path)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="资源不存在")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="资源不存在")
    return FileResponse(path)


@router.post("/jobs/{job_id}/annotations/{annotation_id}", response_model=ProcessJob)
def update_job_annotation(job_id: str, annotation_id: str, request: AnnotationUpdateRequest) -> ProcessJob:
    try:
        job = job_service.get(job_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="任务不存在")

    updated = False
    for explanation in job.explanations:
        for page_explanation in explanation.page_explanations:
            annotations = page_explanation.annotation_result.annotations
            for index, annotation in enumerate(annotations):
                if annotation.annotation_id != annotation_id:
                    continue
                candidate = request.annotation
                asset = page_explanation.page_asset
                if asset and asset.width and asset.height:
                    candidate = convert_annotation_region_to_ratio(
                        candidate, asset.width, asset.height
                    )
                normalized = normalize_annotation(
                    candidate,
                    page=page_explanation.page,
                    file_index=explanation.file_index,
                    index=index + 1,
                )
                annotations[index] = normalized
                updated = True
            page_explanation.annotation_result.export_rows = rebuild_export_rows(annotations)
            page_explanation.annotation_result.review_required_count = sum(
                1
                for item in annotations
                if item.review_status in {"pending", "needs_manual_review"}
            )
        explanation.annotation_result = merge_annotation_results(
            [item.annotation_result for item in explanation.page_explanations]
        )
    if not updated:
        raise HTTPException(status_code=404, detail="标注不存在")

    explanations = [
        bubble_diagram_service.generate(explanation, job_service.bubbles_dir(job_id))
        for explanation in job.explanations
    ]
    csv_path, _ = export_service.export_annotations(explanations, job_service.exports_dir(job_id))
    for explanation in explanations:
        for page_explanation in explanation.page_explanations:
            if page_explanation.bubble_asset:
                page_explanation.bubble_asset.export_csv_path = str(csv_path)
                page_explanation.bubble_asset.export_csv_url = f"exports/{csv_path.name}"
        if explanation.bubble_asset:
            explanation.bubble_asset.export_csv_path = str(csv_path)
            explanation.bubble_asset.export_csv_url = f"exports/{csv_path.name}"
    job.explanations = explanations
    return job_service.save(job)


@router.post("/jobs/{job_id}/bubble/regenerate", response_model=ProcessJob)
def regenerate_job_bubbles(job_id: str) -> ProcessJob:
    try:
        job = job_service.get(job_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="任务不存在")
    explanations = [
        bubble_diagram_service.generate(explanation, job_service.bubbles_dir(job_id))
        for explanation in job.explanations
    ]
    csv_path, _ = export_service.export_annotations(explanations, job_service.exports_dir(job_id))
    for explanation in explanations:
        if explanation.bubble_asset:
            explanation.bubble_asset.export_csv_path = str(csv_path)
            explanation.bubble_asset.export_csv_url = f"exports/{csv_path.name}"
    job.explanations = explanations
    return job_service.save(job)


@router.post("/generate-from-text", response_model=ProcessGenerationResponse)
async def generate_from_text(request: GenerateFromTextRequest) -> ProcessGenerationResponse:
    agent_response = await process_agent.run_from_text(request.text, request.mode)
    return ProcessGenerationResponse(
        parse_result=agent_response.parse_result,
        annotation_result=agent_response.annotation_result,
        process_plan=agent_response.process_plan,
        flow=agent_response.flow,
        similar_cases=agent_response.similar_cases,
        ai_suggestions=agent_response.ai_suggestions,
        agent_trace=agent_response.agent_trace,
    )


@router.post("/generate-from-parse", response_model=ProcessGenerationResponse)
async def generate_from_parse(request: GenerateFromParseRequest) -> ProcessGenerationResponse:
    process_plan = generator.generate(
        request.parse_result,
        request.mode,
        external_conditions=request.external_conditions
    )
    process_plan, ai_suggestions = await _apply_ai_enhancement(
        process_plan,
        request.parse_result,
        request.use_ai_enhancement,
    )
    flow = flow_builder.build(process_plan)
    
    # 获取相似案例
    similar_cases_data = []
    try:
        drawing_info = request.parse_result.model_dump()
        similar_cases = case_service.get_similar_cases(drawing_info, limit=3)
        similar_cases_data = [
            {
                "case_id": case.case_id,
                "case_name": case.case_name,
                "quality": case.quality,
                "tags": case.tags
            }
            for case in similar_cases
        ]
    except Exception:
        pass
    
    return ProcessGenerationResponse(
        parse_result=request.parse_result,
        process_plan=process_plan,
        flow=flow,
        similar_cases=similar_cases_data,
        ai_suggestions=ai_suggestions
    )


@router.post("/upload", response_model=ProcessGenerationResponse)
async def upload_and_generate(
    file: UploadFile,
    mode: ProcessMode = ProcessMode.STANDARD_8,
    use_ai_enhancement: bool = False,
) -> ProcessGenerationResponse:
    upload_dir = Path("./uploads")
    upload_dir.mkdir(exist_ok=True, parents=True)
    temp_path = await _store_upload(file, upload_dir)

    _, _, result = await _run_sync_explanation_pipeline([str(temp_path)], mode)
    return result


@router.post("/upload-batch", response_model=ProcessGenerationResponse)
async def upload_batch_and_generate(
    files: list[UploadFile] = File(...),
    mode: ProcessMode = ProcessMode.STANDARD_8,
    use_ai_enhancement: bool = False,
) -> ProcessGenerationResponse:
    if not files:
        raise HTTPException(status_code=400, detail="请至少上传 1 个图纸文件")

    upload_dir = Path("./uploads")
    upload_dir.mkdir(exist_ok=True, parents=True)

    temp_paths = [await _store_upload(file, upload_dir) for file in files]

    _, _, result = await _run_sync_explanation_pipeline([str(path) for path in temp_paths], mode)
    return result


@router.post("/agent/upload", response_model=ProcessGenerationResponse)
async def agent_upload_and_generate(
    file: UploadFile,
    mode: ProcessMode = ProcessMode.STANDARD_8,
) -> ProcessGenerationResponse:
    return await upload_and_generate(file=file, mode=mode, use_ai_enhancement=True)


@router.post("/archive", response_model=ArchiveResponse)
def archive_process_plan(request: GenerateFromParseRequest) -> ArchiveResponse:
    process_plan = generator.generate(request.parse_result, request.mode)
    flow = flow_builder.build(process_plan)
    archive_path = export_service.archive_markdown(process_plan, flow)
    markdown = export_service.to_markdown(process_plan, flow)
    return ArchiveResponse(path=str(archive_path), markdown=markdown)


@router.post("/confirm-edited", response_model=ArchiveResponse)
def confirm_edited_plan(request: EditedPlanRequest) -> ArchiveResponse:
    flow = flow_builder.build(request.process_plan)
    markdown = export_service.to_markdown(request.process_plan, flow)
    archive_path = export_service.archive_markdown(request.process_plan, flow) if request.archive else ""
    return ArchiveResponse(path=str(archive_path), markdown=markdown)