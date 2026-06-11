from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ProcessDrawingStage = Literal[
    "blank_rough",
    "semi_finish",
    "finish_inspection",
    "custom",
]

ProcessDrawingViewType = Literal[
    "crankshaft_side_outline",
    "crankshaft_process_state",
    "crankshaft_final_inspection",
    "annotation_table",
    "operation_table",
    "custom",
]

ProcessDrawingAssetType = Literal["json", "svg", "png", "dxf", "pdf"]

ProcessDrawingAssetStatus = Literal["pending", "generated", "failed"]


class ProcessDrawingAsset(BaseModel):
    asset_type: ProcessDrawingAssetType
    file_name: str = ""
    file_path: str = ""
    file_url: str = ""
    width: int = 0
    height: int = 0
    status: ProcessDrawingAssetStatus = "pending"
    message: str = ""


class ProcessDrawingCallout(BaseModel):
    callout_id: str
    label: str
    text: str
    target: str = ""
    target_feature: str = ""
    related_operation_nos: list[str] = Field(default_factory=list)
    related_annotation_ids: list[str] = Field(default_factory=list)
    position: dict[str, float | str] = Field(default_factory=dict)
    style: dict[str, Any] = Field(default_factory=dict)
    requires_manual_review: bool = False
    review_reason: str = ""


class ProcessDrawingView(BaseModel):
    view_id: str
    title: str
    view_type: ProcessDrawingViewType = "crankshaft_process_state"
    source: Literal["template", "drawing", "agent", "manual"] = "template"
    source_page: int | None = None
    source_region: dict[str, float | str] = Field(default_factory=dict)
    highlight_features: list[str] = Field(default_factory=list)
    hidden_features: list[str] = Field(default_factory=list)
    operation_nos: list[str] = Field(default_factory=list)
    annotation_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    geometry: dict[str, Any] = Field(default_factory=dict)
    callouts: list[ProcessDrawingCallout] = Field(default_factory=list)


class ProcessDrawingSheet(BaseModel):
    sheet_no: str
    title: str
    stage: ProcessDrawingStage = "custom"
    related_operation_nos: list[str] = Field(default_factory=list)
    summary: str = ""
    views: list[ProcessDrawingView] = Field(default_factory=list)
    callouts: list[ProcessDrawingCallout] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    assets: list[ProcessDrawingAsset] = Field(default_factory=list)
    requires_manual_review: bool = False
    review_reason: str = ""


class ProcessDrawingPlan(BaseModel):
    plan_id: str
    case_id: str = ""
    job_id: str = ""
    part_name: str = ""
    drawing_no: str = ""
    title: str
    version: str = "draft-v1"
    objective: str = "生成可供工艺人员复核的细分工艺图草稿。"
    source_operation_nos: list[str] = Field(default_factory=list)
    source_annotation_ids: list[str] = Field(default_factory=list)
    sheets: list[ProcessDrawingSheet] = Field(default_factory=list)
    assets: list[ProcessDrawingAsset] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    handoff: list[str] = Field(default_factory=list)
    requires_manual_review: bool = True