from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class EquipmentStatus(str, Enum):
    AVAILABLE = "available"
    BUSY = "busy"
    MAINTENANCE = "maintenance"
    UNAVAILABLE = "unavailable"


class Equipment(BaseModel):
    """生产设备信息"""
    equipment_id: str
    equipment_name: str
    equipment_type: str  # 例如：数控车床、磨床、探伤设备等
    status: EquipmentStatus = EquipmentStatus.AVAILABLE
    capacity: Optional[str] = None  # 产能描述
    specifications: dict[str, str] = Field(default_factory=dict)  # 设备规格
    available_from: Optional[datetime] = None
    notes: Optional[str] = None


class OrderConstraints(BaseModel):
    """订单约束条件"""
    order_no: Optional[str] = None
    quantity: int = 1
    delivery_date: Optional[date] = None
    priority: str = "normal"  # normal, urgent, standard
    special_requirements: List[str] = Field(default_factory=list)
    customer_notes: Optional[str] = None


class ProductionConstraints(BaseModel):
    """生产约束条件"""
    available_equipment: List[Equipment] = Field(default_factory=list)
    order_info: Optional[OrderConstraints] = None
    shift_hours: int = 8  # 每班工作小时数
    max_setup_changes: Optional[int] = None  # 最大换模次数
    preferred_batch_size: Optional[int] = None
    quality_level: str = "standard"  # standard, high_precision, aerospace
    cost_priority: bool = False  # 是否优先考虑成本
    time_priority: bool = False  # 是否优先考虑交期


class ExternalConditions(BaseModel):
    """外部条件汇总"""
    production_constraints: Optional[ProductionConstraints] = None
    enterprise_standards: dict[str, str] = Field(default_factory=dict)  # 企业标准
    historical_preferences: dict[str, str] = Field(default_factory=dict)  # 历史偏好
    remarks: Optional[str] = None
