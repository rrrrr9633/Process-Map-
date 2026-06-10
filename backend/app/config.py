from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings


BASE_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    # AI 大模型配置
    ai_model_provider: str = "openai"
    ai_api_key: str = ""
    ai_api_base: str = "http://new.zhushouzl.cloud/v1"
    ai_model_name: str = "gpt-5.5"
    ai_timeout_seconds: float = 500

    # OCR 配置
    ocr_provider: str = "none"
    ocr_api_key: str = ""
    ocr_api_secret: str = ""

    # 视觉识别配置
    vision_provider: str = "openai"
    vision_api_key: str = ""
    vision_api_base: str = "http://new.zhushouzl.cloud/v1"
    vision_model: str = "gpt-5.5"

    # Agent 配置
    agent_enabled: bool = True
    agent_max_images: int = 20
    agent_max_pdf_pages: int = 20
    agent_max_views_per_page: int = 4
    agent_max_pdf_text_chars: int = 12000
    agent_goal: str = "根据 PDF 图纸中的复杂图片和标注拆分为可执行工艺流程图"

    # 应用配置
    app_env: str = "production"
    debug: bool = False
    public_api_base: str = "https://tianxiadiyi.xyz"
    public_server_ip: str = "154.201.65.69"
    allowed_origins: str = (
        "https://tianxiadiyi.xyz,"
        "http://tianxiadiyi.xyz,"
        "https://154.201.65.69,"
        "http://154.201.65.69,"
        "http://localhost:8000,"
        "http://127.0.0.1:8000,"
        "http://localhost:8080,"
        "http://127.0.0.1:8080,"
        "http://localhost:5173,"
        "http://127.0.0.1:5173"
    )

    # 数据路径
    archive_path: Path = Path("./archives")
    knowledge_base_path: Path = Path("./knowledge_base")

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]

    class Config:
        env_file = ENV_FILE
        case_sensitive = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.archive_path.mkdir(exist_ok=True, parents=True)
        self.knowledge_base_path.mkdir(exist_ok=True, parents=True)


settings = Settings()