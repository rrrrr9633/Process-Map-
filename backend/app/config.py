from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings


BASE_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    # AI 大模型配置
    ai_model_provider: str = ""
    ai_api_key: str = ""
    ai_api_base: str = ""
    ai_model_name: str = ""
    ai_timeout_seconds: float = 500
    ai_active_profile: str = "default"

    # 可切换模型档案：配置页只切换档案，不暴露密钥
    openai_model_provider: str = "openai_compatible"
    openai_api_key: str = ""
    openai_api_base: str = "https://api.openai.com/v1"
    openai_model_name: str = ""
    openai_timeout_seconds: float = 500

    ark_model_provider: str = "ark_responses"
    ark_api_key: str = ""
    ark_api_base: str = "https://ark.cn-beijing.volces.com/api/v3"
    ark_model_name: str = "doubao-seed-2-0-pro-260215"
    ark_timeout_seconds: float = 500

    gpt55_model_provider: str = "openai_compatible"
    gpt55_api_key: str = ""
    gpt55_api_base: str = ""
    gpt55_model_name: str = "gpt-5.5"
    gpt55_timeout_seconds: float = 500

    doubao_visionpro_model_provider: str = "openai_compatible"
    doubao_visionpro_api_key: str = ""
    doubao_visionpro_api_base: str = ""
    doubao_visionpro_model_name: str = "doubao-vision-pro"
    doubao_visionpro_timeout_seconds: float = 500

    # OCR 配置
    ocr_provider: str = "none"
    ocr_api_key: str = ""
    ocr_api_secret: str = ""

    # 视觉识别配置
    vision_provider: str = ""
    vision_api_key: str = ""
    vision_api_base: str = ""
    vision_model: str = ""

    # Agent 配置
    agent_enabled: bool = True
    agent_max_images: int = 20
    agent_max_pdf_pages: int = 20
    agent_max_views_per_page: int = 4
    agent_max_pdf_text_chars: int = 12000
    agent_goal: str = "根据 3D 模型、PDF 图纸、CAD 预览和工程标注拆分为人能看懂的可执行工艺流程图"

    # 数据库配置
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "cutr"
    mysql_charset: str = "utf8mb4"

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
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            f"?charset={self.mysql_charset}"
        )

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
