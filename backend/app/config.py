from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # AI 大模型配置
    ai_model_provider: str = "deepseek"
    ai_api_key: str = ""
    ai_api_base: str = "https://api.deepseek.com/v1"
    ai_model_name: str = "deepseek-chat"
    ai_timeout_seconds: float = 45
    
    # OCR 配置
    ocr_provider: str = "none"
    ocr_api_key: str = ""
    ocr_api_secret: str = ""
    
    # 视觉识别配置
    vision_provider: str = "none"
    vision_api_key: str = ""
    vision_api_base: str = ""
    vision_model: str = ""

    # Agent 配置
    agent_enabled: bool = True
    agent_max_images: int = 1
    agent_max_pdf_text_chars: int = 12000
    agent_goal: str = "根据 PDF 图纸中的复杂图片和标注拆分为可执行工艺流程图"
    
    # 应用配置
    app_env: str = "development"
    debug: bool = True
    
    # 数据路径
    archive_path: Path = Path("./archives")
    knowledge_base_path: Path = Path("./knowledge_base")
    
    class Config:
        env_file = ".env"
        case_sensitive = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 确保目录存在
        self.archive_path.mkdir(exist_ok=True, parents=True)
        self.knowledge_base_path.mkdir(exist_ok=True, parents=True)


settings = Settings()
