from __future__ import annotations

from app.models.drawing import DrawingParseResult, RequirementType
from app.models.process import ProcessPlan, ValidationIssue
from app.rules.crankshaft_rules import REQUIREMENT_RULES


class ProcessValidator:
    def validate(self, parse_result: DrawingParseResult, plan: ProcessPlan) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        issues.extend(self._validate_operation_count(plan))
        issues.extend(self._validate_required_requirements(parse_result, plan))
        issues.extend(self._validate_manual_review(parse_result))
        return issues

    def _validate_operation_count(self, plan: ProcessPlan) -> list[ValidationIssue]:
        if any("agent_reasoning" in operation.triggered_by or "pdf_image" in operation.triggered_by for operation in plan.operations):
            return []
        expected = 8 if plan.mode.value == "standard_8" else 10
        if len(plan.operations) != expected:
            return [
                ValidationIssue(
                    code="operation_count_mismatch",
                    message=f"当前模式应输出 {expected} 道工序，实际为 {len(plan.operations)} 道",
                    severity="critical",
                )
            ]
        return []

    def _validate_required_requirements(self, parse_result: DrawingParseResult, plan: ProcessPlan) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        plan_text = "\n".join(
            [
                operation.operation_name
                + "\n"
                + operation.content
                + "\n"
                + "\n".join(operation.control_points)
                + "\n"
                + "\n".join(operation.inspection_items)
                for operation in plan.operations
            ]
        )

        detected_types = {requirement.type for requirement in parse_result.technical_requirements}
        for requirement_type in detected_types:
            rule = REQUIREMENT_RULES.get(requirement_type)
            if not rule:
                continue
            if not any(term in plan_text for term in rule["required_terms"]):
                issues.append(
                    ValidationIssue(
                        code=f"missing_{requirement_type.value}",
                        message=f"图纸触发了 {requirement_type.value}，但工序文本中未覆盖对应强制节点或管控点",
                        severity="critical",
                    )
                )

        if RequirementType.DEMAGNETIZATION in detected_types and RequirementType.MAGNETIC_PARTICLE_TESTING not in detected_types:
            issues.append(
                ValidationIssue(
                    code="demagnetization_without_testing",
                    message="识别到退磁要求，但未识别到探伤要求，建议人工核对技术要求",
                    severity="warning",
                )
            )
        return issues

    def _validate_manual_review(self, parse_result: DrawingParseResult) -> list[ValidationIssue]:
        return [
            ValidationIssue(code="parse_risk", message=flag.message, severity=flag.severity)
            for flag in parse_result.risk_flags
            if flag.severity in {"warning", "critical"}
        ]