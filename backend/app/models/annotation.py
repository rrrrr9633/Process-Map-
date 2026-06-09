from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    page: int = 1
    x: float = 0
    y: float = 0
    width: float = 0
    height: float = 0
    unit: Literal["pixel", "ratio"] = "ratio"


class DrawingAnnotation(BaseModel):
    annotation_id: str
    label: Optional[str] = None
    region: BoundingBox = Field(default_factory=BoundingBox)
    raw_text: str = ""
    normalized_text: Optional[str] = None
    parameter_name: Optional[str] = None
    parameter_value: Optional[str] = None
    upper_limit: Optional[str] = None
    lower_limit: Optional[str] = None
    unit: Optional[str] = None
    semantic_type: Literal[
        "dimension",
        "tolerance",
        "roughness",
        "datum",
        "geometric_tolerance",
        "material",
        "process_note",
        "inspection_note",
        "quality_note",
        "unknown",
    ] = "unknown"
    source: Literal["pdf_text", "pdf_page_image", "pdf_embedded_image", "agent_reasoning", "manual"] = "agent_reasoning"
    confidence: float = 0.5
    review_status: Literal["pending", "accepted", "rejected", "needs_manual_review"] = "pending"
    review_reason: Optional[str] = None


class AnnotationExportRow(BaseModel):
    row_no: int
    annotation_id: str
    parameter_name: str
    parameter_value: str = ""
    upper_limit: str = ""
    lower_limit: str = ""
    unit: str = ""
    semantic_type: str = "unknown"
    review_status: str = "pending"
    source: str = "agent_reasoning"
    confidence: float = 0.5


class DrawingAnnotationResult(BaseModel):
    annotations: List[DrawingAnnotation] = Field(default_factory=list)
    export_rows: List[AnnotationExportRow] = Field(default_factory=list)
    bubble_diagram_available: bool = False
    review_required_count: int = 0