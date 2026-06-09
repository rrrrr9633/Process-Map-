import hashlib
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.models.drawing import DrawingParseResult
from app.models.process import ProcessMode, ProcessPlan
from app.schemas.process import EditedPlanRequest, GenerateFromParseRequest, GenerateFromTextRequest, ProcessGenerationResponse
from app.services.ai_service import AIServiceError, ai_service
from app.services.case_service import case_service
from app.services.drawing_parser import DrawingParser
from app.services.export_service import ExportService
from app.services.flow_builder import FlowBuilder
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

    agent_response = await process_agent.run_from_file(temp_path, mode)
    return ProcessGenerationResponse(
        parse_result=agent_response.parse_result,
        annotation_result=agent_response.annotation_result,
        process_plan=agent_response.process_plan,
        flow=agent_response.flow,
        similar_cases=agent_response.similar_cases,
        ai_suggestions=agent_response.ai_suggestions,
        agent_trace=agent_response.agent_trace,
    )


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

    agent_response = await process_agent.run_from_files(temp_paths, mode)
    return ProcessGenerationResponse(
        parse_result=agent_response.parse_result,
        annotation_result=agent_response.annotation_result,
        process_plan=agent_response.process_plan,
        flow=agent_response.flow,
        similar_cases=agent_response.similar_cases,
        ai_suggestions=agent_response.ai_suggestions,
        agent_trace=agent_response.agent_trace,
    )


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