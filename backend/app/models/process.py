from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class ProcessMode(str, Enum):
    STANDARD_8 = "standard_8"
    DETAILED_10 = "detailed_10"


class OperationType(str, Enum):
    BLANK_PREPARATION = "blank_preparation"
    BASELINE_PROCESSING = "baseline_processing"
    ROUGH_MACHINING = "rough_machining"
    SEMI_FINISHING = "semi_finishing"
    HOLE_PROCESSING = "hole_processing"
    FINISHING = "finishing"
    INSPECTION = "inspection"
    SPECIAL_PROCESS = "special_process"
    CLEANING_FINAL_INSPECTION = "cleaning_final_inspection"


class Operation(BaseModel):
    operation_no: str
    operation_name: str
    operation_type: OperationType
    targets: List[str] = Field(default_factory=list)
    content: str
    worker_steps: List[str] = Field(default_factory=list)
    materials: List[str] = Field(default_factory=list)
    tools: List[str] = Field(default_factory=list)
    setup_requirements: List[str] = Field(default_factory=list)
    safety_points: List[str] = Field(default_factory=list)
    quality_gates: List[str] = Field(default_factory=list)
    handoff_requirements: List[str] = Field(default_factory=list)
    control_points: List[str] = Field(default_factory=list)
    equipment: List[str] = Field(default_factory=list)
    inspection_items: List[str] = Field(default_factory=list)
    drawing_basis: List[str] = Field(default_factory=list)
    mandatory: bool = False
    requires_manual_review: bool = False
    triggered_by: List[str] = Field(default_factory=list)


class ValidationIssue(BaseModel):
    code: str
    message: str
    severity: Literal["info", "warning", "critical"] = "warning"
    operation_no: Optional[str] = None


class ProcessPlan(BaseModel):
    mode: ProcessMode
    title: str
    operations: List[Operation]
    validation_issues: List[ValidationIssue] = Field(default_factory=list)
    requires_manual_review: bool = False