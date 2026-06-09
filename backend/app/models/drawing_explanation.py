from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.annotation import DrawingAnnotation, DrawingAnnotationResult


JobStage = Literal[
    "uploaded",
    "rendering",
    "explaining",
    "bubble_generating",
    "flow_generating",
    "completed",
    "failed",
]


class DrawingPageAsset(BaseModel):
    file_index: int
    file_name: str
    page: int = 1
    image_path: str
    image_url: str
    width: int = 0
    height: int = 0


class BubbleDiagramAsset(BaseModel):
    file_index: int
    file_name: str
    page: int = 1
    image_path: str = ""
    image_url: str = ""
    export_csv_path: str = ""
    export_csv_url: str = ""
    status: Literal["pending", "generated", "failed"] = "pending"
    message: str = ""



class DrawingViewExplanation(BaseModel):
    view_index: int = 1
    label: str = "整页"
    region: dict[str, float | str] = Field(default_factory=dict)
    visual_summary: str = ""
    detected_features: list[str] = Field(default_factory=list)
    related_operations: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)


class DrawingPageExplanation(BaseModel):
    page: int
    page_asset: DrawingPageAsset | None = None
    view_explanations: list[DrawingViewExplanation] = Field(default_factory=list)
    visual_summary: str = ""
    detected_features: list[str] = Field(default_factory=list)
    related_operations: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    annotation_result: DrawingAnnotationResult = Field(default_factory=DrawingAnnotationResult)
    bubble_asset: BubbleDiagramAsset | None = None


class DrawingExplanation(BaseModel):
    file_index: int
    file_name: str
    source_path: str
    page_index: int = 1
    page_count: int = 1
    page_asset: DrawingPageAsset | None = None
    page_explanations: list[DrawingPageExplanation] = Field(default_factory=list)
    visual_summary: str = ""
    detected_features: list[str] = Field(default_factory=list)
    related_operations: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    annotation_result: DrawingAnnotationResult = Field(default_factory=DrawingAnnotationResult)
    bubble_asset: BubbleDiagramAsset | None = None


class ProcessJob(BaseModel):
    job_id: str
    stage: JobStage = "uploaded"
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    progress: int = 0
    message: str = "已接收任务"
    files: list[str] = Field(default_factory=list)
    explanations: list[DrawingExplanation] = Field(default_factory=list)
    process_result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class AnnotationUpdateRequest(BaseModel):
    annotation: DrawingAnnotation