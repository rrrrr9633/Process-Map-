from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class FlowNodeType(str, Enum):
    MACHINING = "machining"
    PRECISION_MACHINING = "precision_machining"
    INSPECTION = "inspection"
    SPECIAL_PROCESS = "special_process"
    CLEANING_FINAL_INSPECTION = "cleaning_final_inspection"
    MANUAL_REVIEW = "manual_review"


class FlowNode(BaseModel):
    id: str
    label: str
    type: FlowNodeType
    operation_no: Optional[str] = None
    control_points: List[str] = Field(default_factory=list)


class FlowEdge(BaseModel):
    source: str
    target: str
    label: Optional[str] = None


class ProcessFlow(BaseModel):
    title: str
    nodes: List[FlowNode]
    edges: List[FlowEdge]
    mermaid: str