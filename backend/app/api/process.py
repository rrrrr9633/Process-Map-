import asyncio
import hashlib
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.models.drawing import DrawingParseResult
from app.models.drawing_explanation import DrawingExplanation, ProcessJob
from app.models.process import ProcessMode, ProcessPlan
from app.schemas.process import EditedPlanRequest, GenerateFromParseRequest, GenerateFromTextRequest, ProcessGenerationResponse
from app.services.ai_service import AIServiceError, ai_service
from app.services.case_service import case_service
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
BACKEND_DIR = Path(__file__).resolve().parents[2]
UPLOADS_DIR = BACKEND_DIR / "uploads"


class ArchiveResponse(BaseModel):
    path: str
    markdown: str


class FromStoredJobRequest(BaseModel):
    stored_names: list[str]
    mode: ProcessMode = ProcessMode.STANDARD_8


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


def _resolve_stored_uploads(stored_names: list[str], upload_dir: Path) -> list[Path]:
    if not stored_names:
        raise HTTPException(status_code=400, detail="请至少指定 1 个已存图纸文件名")
    paths: list[Path] = []
    upload_root = upload_dir.resolve()
    for raw_name in stored_names:
        safe_name = Path(raw_name).name
        if not safe_name or safe_name in {".", ".."}:
            raise HTTPException(status_code=400, detail=f"无效文件名：{raw_name}")
        suffix = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
        if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
            raise HTTPException(status_code=400, detail=f"暂不支持的文件格式：{safe_name}")
        path = (upload_dir / safe_name).resolve()
        if upload_root not in path.parents:
            raise HTTPException(status_code=400, detail=f"非法路径：{raw_name}")
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"uploads 中不存在：{safe_name}")
        paths.append(path)
    return paths


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
    """同步兼容接口：只生成快速工序层；精细图解、气泡图和标注全部移入案例后台。"""
    job = job_service.create_job(file_paths)
    job_id = job.job_id
    agent_response = await process_agent.run_from_files(file_paths, mode, explanations=None)
    result = ProcessGenerationResponse(
        parse_result=agent_response.parse_result,
        annotation_result=agent_response.annotation_result,
        process_plan=agent_response.process_plan,
        flow=agent_response.flow,
        similar_cases=agent_response.similar_cases,
        ai_suggestions=agent_response.ai_suggestions,
        agent_trace=agent_response.agent_trace,
        job_id=job_id,
        explanations=[],
    )
    job_service.set_process_result(job_id, result.model_dump(mode="json"))
    job_service.complete(job_id)
    return job_id, [], result

async def _run_process_job(job_id: str, file_paths: list[str], mode: ProcessMode) -> None:
    try:
        total = max(1, len(file_paths))
        job_service.update(
            job_id,
            stage="flow_generating",
            status="running",
            progress=10,
            message=f"快速层：正在基于 {total} 份图纸生成工艺流程",
            ai_stream_preview="AI 快速工艺流程请求已发出，正在等待模型返回第一段内容",
            ai_stream_chunks=0,
        )

        def on_flow_stream_delta(delta: str, chunk_count: int, content: str) -> None:
            progress = min(95, 10 + chunk_count // 6)
            job_service.update(
                job_id,
                stage="flow_generating",
                status="running",
                progress=progress,
                message=f"快速层：AI 正在生成工艺流程，已接收 {chunk_count} 段内容",
                ai_stream_preview=content,
                ai_stream_chunks=chunk_count,
            )

        agent_response = await process_agent.run_from_files(
            file_paths,
            mode,
            explanations=None,
            on_stream_delta=on_flow_stream_delta,
        )
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
        error = f"{type(exc).__name__}: {exc}"
        try:
            current_job = job_service.get(job_id)
            if current_job.ai_stream_chunks > 0:
                error = f"AI 已返回 {current_job.ai_stream_chunks} 段内容，但结果解析或写入失败：{error}"
        except Exception:
            pass
        job_service.fail(job_id, error)


@router.post("/jobs/from-stored", response_model=ProcessJob)
async def create_job_from_stored(
    request: FromStoredJobRequest,
    background_tasks: BackgroundTasks,
) -> ProcessJob:
    upload_dir = UPLOADS_DIR
    upload_dir.mkdir(exist_ok=True, parents=True)
    paths = _resolve_stored_uploads(request.stored_names, upload_dir)
    path_strings = [str(path) for path in paths]
    print(
        f"[process] reuse stored uploads for job: {[path.name for path in paths]}",
        flush=True,
    )
    job = job_service.create_job(path_strings)
    background_tasks.add_task(_run_process_job, job.job_id, path_strings, request.mode)
    return job


@router.post("/jobs/upload-batch", response_model=ProcessJob)
async def upload_batch_job(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    mode: ProcessMode = ProcessMode.STANDARD_8,
) -> ProcessJob:
    if not files:
        raise HTTPException(status_code=400, detail="请至少上传 1 个图纸文件")

    upload_dir = UPLOADS_DIR
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
    except Exception as exc:
        return ProcessJob(
            job_id=job_id,
            stage="failed",
            status="failed",
            progress=100,
            message="任务状态读取失败",
            error=f"{type(exc).__name__}: {exc}",
        )


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
    upload_dir = UPLOADS_DIR
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

    upload_dir = UPLOADS_DIR
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