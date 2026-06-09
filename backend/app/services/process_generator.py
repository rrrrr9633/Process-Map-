from __future__ import annotations

from typing import Optional

from app.models.drawing import DrawingParseResult, RequirementType
from app.models.process import ProcessMode, ProcessPlan
from app.rules.crankshaft_rules import REQUIREMENT_RULES, get_templates
from app.services.process_validator import ProcessValidator


FINISHING_REQUIREMENTS = {RequirementType.ROLLING, RequirementType.GRINDING, RequirementType.POLISHING, RequirementType.NO_CHAMFER}
INSPECTION_REQUIREMENTS = {
    RequirementType.MAGNETIC_PARTICLE_TESTING,
    RequirementType.DEMAGNETIZATION,
    RequirementType.DYNAMIC_BALANCING,
    RequirementType.GROUP_MARKING,
    RequirementType.MULTI_SECTION_MEASUREMENT,
}
CLEANING_REQUIREMENTS = {RequirementType.CLEANLINESS}


class ProcessGenerator:
    def __init__(self) -> None:
        self.validator = ProcessValidator()

    def generate(
        self,
        parse_result: DrawingParseResult,
        mode: ProcessMode,
        external_conditions: Optional[dict] = None
    ) -> ProcessPlan:
        operations = [template.to_operation() for template in get_templates(mode)]
        self._inject_detected_features(parse_result, operations)
        self._inject_special_requirements(parse_result, operations)
        
        # 根据外部条件调整工序
        if external_conditions:
            self._apply_external_conditions(operations, external_conditions)

        plan = ProcessPlan(
            mode=mode,
            title=self._build_title(parse_result, mode),
            operations=operations,
            requires_manual_review=bool(parse_result.risk_flags),
        )
        plan.validation_issues = self.validator.validate(parse_result, plan)
        plan.requires_manual_review = plan.requires_manual_review or any(
            issue.severity in {"warning", "critical"} for issue in plan.validation_issues
        )
        return plan

    def _build_title(self, parse_result: DrawingParseResult, mode: ProcessMode) -> str:
        part_name = parse_result.part.part_name or "曲轴"
        suffix = "8道标准工序" if mode == ProcessMode.STANDARD_8 else "10道精细工序"
        return f"{part_name}{suffix}方案"

    def _inject_detected_features(self, parse_result: DrawingParseResult, operations) -> None:
        feature_names = [feature.name for feature in parse_result.features]
        if not feature_names:
            return
        basis = f"识别到加工特征：{'、'.join(feature_names)}"
        for operation in operations:
            if operation.operation_no in {"03", "04", "05", "06", "07", "08", "09"}:
                operation.drawing_basis.append(basis)

    def _inject_special_requirements(self, parse_result: DrawingParseResult, operations) -> None:
        for requirement in parse_result.technical_requirements:
            rule = REQUIREMENT_RULES.get(requirement.type)
            if not rule:
                continue
            target_operation = self._find_target_operation(requirement.type, operations)
            target_operation.control_points.append(rule["control_point"])
            target_operation.drawing_basis.append(requirement.source_text or requirement.content)
            target_operation.triggered_by.append(requirement.type.value)
            target_operation.mandatory = True

    def _find_target_operation(self, requirement_type: RequirementType, operations):
        if requirement_type in FINISHING_REQUIREMENTS:
            return self._first_by_keywords(operations, ("精磨", "滚压", "精加工"))
        if requirement_type in INSPECTION_REQUIREMENTS:
            return self._first_by_keywords(operations, ("检测", "探伤", "动平衡", "打刻", "分组"))
        if requirement_type in CLEANING_REQUIREMENTS:
            return self._first_by_keywords(operations, ("清洗", "终检"))
        return operations[-1]

    def _first_by_keywords(self, operations, keywords: tuple[str, ...]):
        for operation in operations:
            text = operation.operation_name + operation.content
            if any(keyword in text for keyword in keywords):
                return operation
        return operations[-1]
    
    def _apply_external_conditions(self, operations, external_conditions: dict) -> None:
        """根据外部条件调整工序"""
        # TODO: 实现外部条件逻辑
        # 例如：
        # - 根据可用设备调整设备选择
        # - 根据交期调整工序合并策略
        # - 根据质量要求调整控制点
        pass