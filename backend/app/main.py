from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.cases import router as cases_router
from app.api.process import router as process_router
from app.config import settings

BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR / "frontend"
INDEX_V2_PATH = FRONTEND_DIR / "index_v2.html"

app = FastAPI(title="曲轴工序拆分系统", version="0.2.0")

# 配置 CORS，允许本地开发地址和公网部署地址访问
allowed_origins = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://154.201.65.69",
    "https://154.201.65.69",
    "http://tianxiadiyi.xyz",
    "https://tianxiadiyi.xyz",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(process_router)
app.include_router(cases_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/config/status")
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