from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.config import settings


@dataclass(frozen=True)
class ModelProfile:
    profile_id: str
    label: str
    provider: str
    api_key: str
    api_base: str
    model: str
    timeout_seconds: float
    description: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_base and self.model)

    def public_dict(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "label": self.label,
            "provider": self.provider,
            "api_base": self.api_base,
            "model": self.model,
            "timeout_seconds": self.timeout_seconds,
            "configured": self.configured,
            "description": self.description,
        }


class ModelProfileService:
    def __init__(self) -> None:
        self.state_path = settings.knowledge_base_path / "active_model_profile.json"
        self.profile_aliases = {
            "doubao_visionpro": "ark_doubao",
        }

    def profiles(self) -> dict[str, ModelProfile]:
        return {
            "default": ModelProfile(
                profile_id="default",
                label="默认环境模型",
                provider=settings.ai_model_provider,
                api_key=settings.ai_api_key,
                api_base=settings.ai_api_base.rstrip("/"),
                model=settings.ai_model_name,
                timeout_seconds=settings.ai_timeout_seconds,
                description="兼容旧 AI_MODEL_* 配置。",
            ),
            "gpt55": ModelProfile(
                profile_id="gpt55",
                label="OpenAI / GPT",
                provider=settings.openai_model_provider,
                api_key=settings.openai_api_key or settings.gpt55_api_key or settings.ai_api_key,
                api_base=(settings.openai_api_base or settings.gpt55_api_base or settings.ai_api_base).rstrip("/"),
                model=settings.openai_model_name or settings.gpt55_model_name,
                timeout_seconds=settings.openai_timeout_seconds,
                description="适合工序推理、最终指导和复杂 JSON 结构化输出。",
            ),
            "ark_doubao": ModelProfile(
                profile_id="ark_doubao",
                label="火山 Ark / 豆包",
                provider=settings.ark_model_provider,
                api_key=settings.ark_api_key or settings.doubao_visionpro_api_key,
                api_base=(settings.ark_api_base or settings.doubao_visionpro_api_base).rstrip("/"),
                model=settings.ark_model_name or settings.doubao_visionpro_model_name,
                timeout_seconds=settings.ark_timeout_seconds,
                description="使用火山 Ark Responses API，适合豆包多模态图纸识别。",
            ),
        }

    def active_profile_id(self) -> str:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            profile_id = str(data.get("active_profile") or "").strip()
            profile_id = self.profile_aliases.get(profile_id, profile_id)
            if profile_id in self.profiles():
                return profile_id
        except Exception:
            pass
        configured_profile = self.profile_aliases.get(settings.ai_active_profile, settings.ai_active_profile)
        return configured_profile if configured_profile in self.profiles() else "default"

    def active_profile(self) -> ModelProfile:
        profiles = self.profiles()
        return profiles.get(self.active_profile_id()) or profiles["default"]

    def set_active_profile(self, profile_id: str) -> ModelProfile:
        profile_id = self.profile_aliases.get(profile_id, profile_id)
        profiles = self.profiles()
        if profile_id not in profiles:
            raise ValueError(f"未知模型档案：{profile_id}")
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.state_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps({"active_profile": profile_id}, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.state_path)
        return profiles[profile_id]

    def status(self) -> dict:
        active_id = self.active_profile_id()
        return {
            "active_profile": active_id,
            "profiles": [profile.public_dict() for profile in self.profiles().values()],
            "active": self.active_profile().public_dict(),
        }


model_profile_service = ModelProfileService()
