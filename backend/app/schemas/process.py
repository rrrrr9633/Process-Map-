from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.agent import AgentRunTrace
from app.models.annotation import DrawingAnnotationResult
from app.models.constraints import ExternalConditions
from app.models.drawing import DrawingParseResult
from app.models.flow import ProcessFlow
from app.models.drawing_explanation import DrawingExplanation
from app.models.process import ProcessMode, ProcessPlan


class GenerateFromTextRequest(BaseModel):
    text: str
    mode: ProcessMode = ProcessMode.STANDARD_8
    external_conditions: Optional[ExternalConditions] = None
    use_ai_enhancement: bool = False


class GenerateFromParseRequest(BaseModel):
    parse_result: DrawingParseResult
    mode: ProcessMode = ProcessMode.STANDARD_8
    external_conditions: Optional[ExternalConditions] = None
    use_ai_enhancement: bool = False


class EditedPlanRequest(BaseModel):
    process_plan: ProcessPlan
    archive: bool = False
    editor_name: Optional[str] = None
    edit_notes: Optional[str] = None


class ProcessGenerationResponse(BaseModel):
    parse_result: DrawingParseResult
    annotation_result: DrawingAnnotationResult = Field(default_factory=DrawingAnnotationResult)
    process_plan: ProcessPlan
    flow: ProcessFlow
    similar_cases: List[dict] = []
    ai_suggestions: List[str] = []
    agent_trace: Optional[AgentRunTrace] = None
    job_id: Optional[str] = None
    explanations: List[DrawingExplanation] = Field(default_factory=list)

