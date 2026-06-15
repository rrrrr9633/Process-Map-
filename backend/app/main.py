from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.api.agent import router as agent_router
from app.api.cases import router as cases_router
from app.api.process import router as process_router
from app.config import settings
from app.db import init_db
from app.services.model_profile_service import model_profile_service

BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR / "frontend"
INDEX_V2_PATH = FRONTEND_DIR / "index_v2.html"

app = FastAPI(title="曲轴工序拆分系统", version="0.2.0")


class ModelProfileSwitchRequest(BaseModel):
    profile_id: str


@app.on_event("startup")
def startup() -> None:
    init_db()


# CORS：生产环境从 ALLOWED_ORIGINS 读取，默认包含 tianxiadiyi.xyz 与服务器 IP。
allowed_origins = settings.cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(process_router)
app.include_router(cases_router)
app.include_router(agent_router)
app.include_router(process_router, prefix="/api")
app.include_router(cases_router, prefix="/api")
app.include_router(agent_router, prefix="/api")


@app.get("/health")
@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/config/status")
@app.get("/api/config/status")
def config_status() -> dict:
    model_profiles = model_profile_service.status()
    active_ai = model_profiles["active"]
    return {
        "api_base": settings.public_api_base,
        "server_ip": settings.public_server_ip,
        "ai": {
            "configured": active_ai["configured"],
            "provider": active_ai["provider"],
            "api_base": active_ai["api_base"],
            "model": active_ai["model"],
            "timeout_seconds": active_ai["timeout_seconds"],
            "active_profile": model_profiles["active_profile"],
        },
        "model_profiles": model_profiles,
        "ocr": {
            "configured": settings.ocr_provider != "none" and bool(settings.ocr_api_key),
            "provider": settings.ocr_provider,
        },
        "vision": {
            "configured": settings.vision_provider != "none" and bool(settings.vision_api_key),
            "provider": settings.vision_provider,
            "api_base": settings.vision_api_base,
        },
        "app_env": settings.app_env,
        "debug": settings.debug,
    }


@app.post("/config/model-profile")
@app.post("/api/config/model-profile")
def switch_model_profile(request: ModelProfileSwitchRequest) -> dict:
    try:
        profile = model_profile_service.set_active_profile(request.profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "message": "模型档案已切换",
        "active_profile": profile.profile_id,
        "active": profile.public_dict(),
    }


@app.get("/", response_class=FileResponse)
def root() -> FileResponse:
    return FileResponse(INDEX_V2_PATH)


app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="frontend")
