from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class GuidanceMetric(BaseModel):
    label: str
    value: str
    note: str = ""


class GuidanceIssue(BaseModel):
    title: str
    detail: str
    severity: Literal["info", "warning", "critical"] = "warning"


class ProcessGuidance(BaseModel):
    feasibility: Literal["high", "medium", "low"]
    feasibility_text: str
    quality_score: float = Field(ge=0, le=5)
    executive_summary: str
    data_readability: str
    recommended_workflow: list[str] = Field(default_factory=list)
    metrics: list[GuidanceMetric] = Field(default_factory=list)
    key_usable_data: list[str] = Field(default_factory=list)
    issues: list[GuidanceIssue] = Field(default_factory=list)
    manual_review: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
