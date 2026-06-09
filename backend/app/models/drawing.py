from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FeatureType(str, Enum):
    # 曲轴专用特征，继续兼容旧规则
    MAIN_JOURNAL = "main_journal"
    ROD_JOURNAL = "rod_journal"
    FLANGE = "flange"
    OIL_HOLE = "oil_hole"
    BOLT_HOLE = "bolt_hole"
    DOWEL_HOLE = "dowel_hole"
    COUNTERWEIGHT = "counterweight"
    MARKING_AREA = "marking_area"
    NO_CHAMFER_AREA = "no_chamfer_area"

    # 通用机械图纸特征，Agent 主链使用
    SHAFT = "shaft"
    HOLE = "hole"
    THREAD = "thread"
    SLOT = "slot"
    GROOVE = "groove"
    KEYWAY = "keyway"
    SURFACE = "surface"
    DATUM = "datum"
    DIMENSION = "dimension"
    TOLERANCE = "tolerance"
    ANNOTATION = "annotation"
    SECTION_VIEW = "section_view"
    DETAIL_VIEW = "detail_view"
    ASSEMBLY_RELATION = "assembly_relation"
    PROCESS_NOTE = "process_note"
    GENERAL_FEATURE = "general_feature"
    UNKNOWN = "unknown"


class RequirementType(str, Enum):
    # 曲轴专用工艺要求，继续兼容旧规则
    ROLLING = "rolling"
    GRINDING = "grinding"
    POLISHING = "polishing"
    MAGNETIC_PARTICLE_TESTING = "magnetic_particle_testing"
    DEMAGNETIZATION = "demagnetization"
    DYNAMIC_BALANCING = "dynamic_balancing"
    CLEANLINESS = "cleanliness"
    GROUP_MARKING = "group_marking"
    NO_CHAMFER = "no_chamfer"
    MULTI_SECTION_MEASUREMENT = "multi_section_measurement"

    # 通用图纸/质检/工艺要求，Agent 主链使用
    DIMENSION_REQUIREMENT = "dimension_requirement"
    TOLERANCE_REQUIREMENT = "tolerance_requirement"
    ROUGHNESS_REQUIREMENT = "roughness_requirement"
    MATERIAL_REQUIREMENT = "material_requirement"
    HEAT_TREATMENT = "heat_treatment"
    SURFACE_TREATMENT = "surface_treatment"
    MACHINING_REQUIREMENT = "machining_requirement"
    INSPECTION_REQUIREMENT = "inspection_requirement"
    QUALITY_REQUIREMENT = "quality_requirement"
    PROCESS_PARAMETER = "process_parameter"
    ANNOTATION_REQUIREMENT = "annotation_requirement"
    GENERAL_REQUIREMENT = "general_requirement"
    UNKNOWN = "unknown"


class PartInfo(BaseModel):
    part_name: Optional[str] = None
    drawing_no: Optional[str] = None
    material: Optional[str] = None
    blank_type: Optional[str] = None
    heat_treatment: Optional[str] = None


class DrawingFeature(BaseModel):
    type: FeatureType
    name: str
    description: Optional[str] = None
    location: Optional[str] = None
    source_text: Optional[str] = None
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM


class ToleranceItem(BaseModel):
    name: str
    nominal: Optional[str] = None
    tolerance: Optional[str] = None
    geometric_tolerance: Optional[str] = None
    roughness: Optional[str] = None
    source_text: Optional[str] = None
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM


class TechnicalRequirement(BaseModel):
    type: RequirementType
    content: str
    source_text: Optional[str] = None
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM


class InspectionRequirement(BaseModel):
    item: str
    method: Optional[str] = None
    acceptance: Optional[str] = None
    source_text: Optional[str] = None
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM


class RiskFlag(BaseModel):
    field: str
    message: str
    severity: Literal["info", "warning", "critical"] = "warning"


class DrawingParseResult(BaseModel):
    part: PartInfo = Field(default_factory=PartInfo)
    features: List[DrawingFeature] = Field(default_factory=list)
    tolerances: List[ToleranceItem] = Field(default_factory=list)
    technical_requirements: List[TechnicalRequirement] = Field(default_factory=list)
    inspection_requirements: List[InspectionRequirement] = Field(default_factory=list)
    risk_flags: List[RiskFlag] = Field(default_factory=list)
    raw_text: Optional[str] = None