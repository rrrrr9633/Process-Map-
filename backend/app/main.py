from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.cases import router as cases_router
from app.api.process import router as process_router
from app.config import settings
from app.db import init_db

BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR / "frontend"
INDEX_V2_PATH = FRONTEND_DIR / "index_v2.html"

app = FastAPI(title="曲轴工序拆分系统", version="0.2.0")


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
app.include_router(process_router, prefix="/api")
app.include_router(cases_router, prefix="/api")


@app.get("/health")
@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/config/status")
@app.get("/api/config/status")
def config_status() -> dict:
    return {
        "api_base": settings.public_api_base,
        "server_ip": settings.public_server_ip,
        "ai": {
            "configured": bool(settings.ai_api_key),
            "provider": settings.ai_model_provider,
            "api_base": settings.ai_api_base,
            "model": settings.ai_model_name,
            "timeout_seconds": settings.ai_timeout_seconds,
        },
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


@app.get("/", response_class=FileResponse)
def root() -> FileResponse:
    return FileResponse(INDEX_V2_PATH)


app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="frontend")