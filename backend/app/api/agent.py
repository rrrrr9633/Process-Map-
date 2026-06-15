from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field
from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.agent_runtime.executor import controlled_agent_executor
from app.agent_runtime.planner import agent_planner
from app.agent_runtime.response import response_module
from app.agent_runtime.session import agent_session_store
from app.agent_tools import init_agent_tools
from app.agent_tools.contracts import AgentToolPermission
from app.agent_tools.manifest import agent_tool_manifest
from app.agent_tools.registry import agent_tool_registry


router = APIRouter(prefix="/agent", tags=["agent"])
BACKEND_DIR = Path(__file__).resolve().parents[2]
AGENT_UPLOADS_DIR = BACKEND_DIR / "uploads" / "agent"
SUPPORTED_AGENT_UPLOAD_SUFFIXES = {
    "pdf",
    "png",
    "jpg",
    "jpeg",
    "webp",
    "bmp",
    "dwg",
    "dxf",
    "stl",
    "obj",
    "ply",
    "step",
    "stp",
    "iges",
    "igs",
    "txt",
    "json",
}


class ReadonlyToolRunRequest(BaseModel):
    goal: str = "受控只读工具调用"
    tool_name: str
    arguments: dict = Field(default_factory=dict)
    input_files: list[str] = Field(default_factory=list)


class ToolRunRequest(BaseModel):
    goal: str = "受控工具调用"
    tool_name: str
    arguments: dict = Field(default_factory=dict)
    input_files: list[str] = Field(default_factory=list)
    max_permission: AgentToolPermission = AgentToolPermission.READ_ONLY
    human_confirmed: bool = False


class AutoAgentRunRequest(BaseModel):
    session_id: str = ""
    goal: str
    user_message: str = ""
    input_files: list[str] = Field(default_factory=list)
    max_permission: AgentToolPermission = AgentToolPermission.READ_ONLY
    max_steps: int = Field(default=5, ge=1, le=12)
    human_confirmed_tools: list[str] = Field(default_factory=list)
    initial_context: dict = Field(default_factory=dict)


class ConfirmToolRunRequest(BaseModel):
    session_id: str = ""
    goal: str = "确认执行工具"
    tool_name: str
    arguments: dict = Field(default_factory=dict)
    input_files: list[str] = Field(default_factory=list)
    max_permission: AgentToolPermission = AgentToolPermission.WRITE


@router.get("/tools")
def list_agent_tools(model_callable_only: bool = True) -> dict:
    init_agent_tools()
    specs = agent_tool_registry.list_specs(
        model_callable_only=model_callable_only,
        max_permission=AgentToolPermission.READ_ONLY,
    )
    return {
        "permission_scope": AgentToolPermission.READ_ONLY.value,
        "tools": [spec.model_dump(mode="json") for spec in specs],
    }


@router.get("/tools/catalog")
def list_agent_tool_catalog(
    model_callable_only: bool = False,
    max_permission: AgentToolPermission = Query(default=AgentToolPermission.WRITE),
) -> dict:
    init_agent_tools()
    specs = agent_tool_registry.list_specs(
        model_callable_only=model_callable_only,
        max_permission=max_permission,
    )
    grouped: dict[str, list[dict]] = {}
    permission_counts: dict[str, int] = {}
    for spec in specs:
        grouped.setdefault(spec.category.value, []).append(spec.model_dump(mode="json"))
        permission_counts[spec.permission.value] = permission_counts.get(spec.permission.value, 0) + 1
    return {
        "permission_scope": max_permission.value,
        "model_callable_only": model_callable_only,
        "count": len(specs),
        "permission_counts": permission_counts,
        "categories": grouped,
        "tools": [spec.model_dump(mode="json") for spec in specs],
    }


@router.get("/manifest")
def get_agent_manifest(max_permission: AgentToolPermission = Query(default=AgentToolPermission.WRITE)) -> dict:
    init_agent_tools()
    return agent_tool_manifest(max_permission=max_permission)


@router.post("/sessions")
def create_agent_session() -> dict:
    session = agent_session_store.get_or_create()
    return {"session": agent_session_store.public_dict(session)}


@router.get("/sessions/{session_id}")
def get_agent_session(session_id: str) -> dict:
    session = agent_session_store.get_or_create(session_id)
    return {"session": agent_session_store.public_dict(session)}


@router.post("/files")
async def upload_agent_files(files: list[UploadFile] = File(...), session_id: str = "") -> dict:
    AGENT_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    stored: list[dict] = []
    for file in files:
        suffix = _upload_suffix(file)
        if suffix not in SUPPORTED_AGENT_UPLOAD_SUFFIXES:
            raise HTTPException(status_code=400, detail=f"暂不支持的 Agent 文件格式：{suffix}")
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail=f"上传文件为空：{file.filename or '未命名文件'}")
        digest = hashlib.sha256(content).hexdigest()
        stored_name = f"{uuid4().hex}.{suffix}"
        path = AGENT_UPLOADS_DIR / stored_name
        path.write_bytes(content)
        stored.append(
            {
                "original_name": file.filename or stored_name,
                "stored_name": stored_name,
                "file_path": str(path.resolve()),
                "size": len(content),
                "sha256": digest,
            }
        )
    if session_id:
        session = agent_session_store.get_or_create(session_id)
        agent_session_store.add_files(session, stored)
    return {"files": stored}


@router.post("/runs/readonly-tool")
def run_readonly_tool(request: ReadonlyToolRunRequest) -> dict:
    init_agent_tools()
    try:
        run = controlled_agent_executor.create_run(goal=request.goal, input_files=request.input_files)
        run = controlled_agent_executor.run_tool(
            run,
            request.tool_name,
            request.arguments,
            max_permission=AgentToolPermission.READ_ONLY,
        )
        if run.status.value == "failed":
            raise HTTPException(status_code=403, detail=run.events[-1].message if run.events else "工具权限不足")
        return run.model_dump(mode="json")
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/runs/tool")
def run_tool(request: ToolRunRequest) -> dict:
    init_agent_tools()
    try:
        run = controlled_agent_executor.create_run(goal=request.goal, input_files=request.input_files)
        run = controlled_agent_executor.run_tool(
            run,
            request.tool_name,
            request.arguments,
            max_permission=request.max_permission,
            human_confirmed=request.human_confirmed,
        )
        if run.status.value == "failed":
            raise HTTPException(status_code=403, detail=run.events[-1].message if run.events else "工具权限不足")
        return run.model_dump(mode="json")
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/runs/auto")
async def run_auto_agent(request: AutoAgentRunRequest) -> dict:
    init_agent_tools()
    try:
        session = agent_session_store.get_or_create(request.session_id or None)
        if request.user_message:
            agent_session_store.append_message(session, role="user", content=request.user_message)
        session_files = [item.get("file_path") for item in session.uploaded_files if item.get("file_path")]
        input_files = list(dict.fromkeys([*session_files, *request.input_files]))
        context = {
            **request.initial_context,
            "session": agent_session_store.public_dict(session),
        }
        run = await agent_planner.run(
            goal=request.goal,
            input_files=input_files,
            user_message=request.user_message,
            max_permission=request.max_permission,
            max_steps=request.max_steps,
            human_confirmed_tools=request.human_confirmed_tools,
            initial_context=context,
        )
        payload = response_module.to_chat_response(run)
        agent_session_store.append_message(session, role="assistant", content=payload["assistant_message"], payload=payload)
        agent_session_store.set_last_run(session, payload)
        payload["session"] = agent_session_store.public_dict(session)
        return payload
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/runs/confirm-tool")
def confirm_agent_tool(request: ConfirmToolRunRequest) -> dict:
    init_agent_tools()
    try:
        session = agent_session_store.get_or_create(request.session_id or None)
        run = controlled_agent_executor.create_run(goal=request.goal, input_files=request.input_files)
        run = controlled_agent_executor.run_tool(
            run,
            request.tool_name,
            request.arguments,
            max_permission=request.max_permission,
            human_confirmed=True,
        )
        payload = response_module.to_chat_response(run)
        agent_session_store.append_message(session, role="user", content=f"确认执行工具：{request.tool_name}")
        agent_session_store.append_message(session, role="assistant", content=payload["assistant_message"], payload=payload)
        agent_session_store.set_last_run(session, payload)
        payload["session"] = agent_session_store.public_dict(session)
        return payload
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _upload_suffix(file: UploadFile) -> str:
    return file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else "bin"
