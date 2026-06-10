from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from app.models.annotation import DrawingAnnotationResult
from app.models.drawing import DrawingParseResult
from app.models.flow import ProcessFlow
from app.models.process import ProcessPlan
from app.models.process_guidance import ProcessGuidance


class AgentArtifact(BaseModel):
    kind: Literal["pdf_text", "pdf_image", "pdf_page_image", "vision_observation", "rule_parse", "annotation_result", "process_plan", "flow", "fallback", "process_guidance"]
    title: str
    content: Union[str, Dict[str, Any], List[Dict[str, Any]]]
    confidence: Optional[float] = None


class AgentQuestion(BaseModel):
    field: str
    question: str
    reason: str
    severity: Literal["info", "warning", "critical"] = "warning"


class AgentRunTrace(BaseModel):
    goal: str
    stages: list[str] = Field(default_factory=list)
    artifacts: list[AgentArtifact] = Field(default_factory=list)
    questions: list[AgentQuestion] = Field(default_factory=list)
    used_ai: bool = False
    used_vision: bool = False
    fallback_used: bool = False


class AgentProcessResponse(BaseModel):
    parse_result: DrawingParseResult
    annotation_result: DrawingAnnotationResult = Field(default_factory=DrawingAnnotationResult)
    process_plan: ProcessPlan
    flow: ProcessFlow
    process_guidance: Optional[ProcessGuidance] = None
    similar_cases: list[dict] = Field(default_factory=list)
    ai_suggestions: list[str] = Field(default_factory=list)
    agent_trace: AgentRunTrace
