from __future__ import annotations

from collections import Counter
from typing import Any

from app.models.annotation import DrawingAnnotationResult
from app.models.drawing import DrawingParseResult
from app.models.process import ProcessPlan
from app.models.process_guidance import GuidanceIssue, GuidanceMetric, ProcessGuidance


class ProcessGuidanceService:
    """Third-layer interpreter: turns agent JSON into readable engineering guidance."""

    def build(
        self,
        *,
        parse_result: DrawingParseResult,
        annotation_result: DrawingAnnotationResult,
        process_plan: ProcessPlan,
        agent_trace: Any | None = None,
    ) -> ProcessGuidance:
        operations = process_plan.operations or []
        annotations = annotation_result.annotations or []
        export_rows = annotation_result.export_rows or []
        risk_flags = parse_result.risk_flags or []
        validation_issues = process_plan.validation_issues or []

        accepted = sum(1 for item in annotations if item.review_status == "accepted")
        review_required = sum(1 for item in annotations if item.review_status in {"pending", "needs_manual_review"})
        low_confidence = sum(1 for item in annotations if item.confidence < 0.75)
        source_counter = Counter(item.source for item in annotations)
        type_counter = Counter(item.semantic_type for item in annotations)

        quality_score = self._evidence_score(
            annotation_count=len(annotations),
            accepted=accepted,
            review_required=review_required,
            low_confidence=low_confidence,
            risk_count=len(risk_flags),
            issue_count=len(validation_issues),
            used_vision=bool(getattr(agent_trace, "used_vision", False)),
        )
        feasibility = "high" if quality_score >= 4.2 else "medium" if quality_score >= 3.0 else "low"

        metrics = [
            GuidanceMetric(label="工序数量", value=f"{len(operations)} 道", note="已生成可展示的流程节点"),
            GuidanceMetric(label="结构化标注", value=f"{len(export_rows) or len(annotations)} 条", note="用于尺寸、公差、技术要求追溯"),
            GuidanceMetric(label="需人工复核", value=f"{review_required + len(validation_issues)} 项", note="含低置信标注和流程校验问题"),
            GuidanceMetric(label="质量评分", value=f"{quality_score:.1f}/5", note="基于证据完整度、置信度和校验风险"),
        ]
        if source_counter:
            metrics.append(
                GuidanceMetric(
                    label="主要来源",
                    value="、".join(f"{key}:{count}" for key, count in source_counter.most_common(3)),
                    note="agent_reasoning 占比高时不能直接投产",
                )
            )

        return ProcessGuidance(
            feasibility=feasibility,
            feasibility_text=self._feasibility_text(feasibility, quality_score),
            quality_score=quality_score,
            executive_summary=self._summary(feasibility, operations, annotations, validation_issues),
            data_readability=self._readability_text(annotations, export_rows, review_required),
            recommended_workflow=[
                "先用 PDF/图片/可渲染 CAD 做多模态识别，产出结构化参数和页面坐标。",
                "再做参数清洗：统一工程符号、去重 annotation_id、修正 semantic_type、标记推理来源。",
                "最后由工艺层只读取 accepted 或人工确认后的关键参数，生成工序节点、质控点和交接要求。",
            ],
            metrics=metrics,
            key_usable_data=self._usable_data(annotations, export_rows, type_counter),
            issues=self._issues(parse_result, process_plan, annotation_result, low_confidence),
            manual_review=self._manual_review_items(parse_result, process_plan, annotation_result),
            next_actions=[
                "把 needs_manual_review 和 pending 标注集中成复核清单，不要直接进入工艺卡。",
                "对形位公差、粗糙度、基准和特殊符号优先回看原图，确认后再更新结构化参数。",
                "保存案例时保留原图页码、坐标、参数行和工序依据，后续同类曲轴可复用。",
            ],
        )

    def _evidence_score(
        self,
        *,
        annotation_count: int,
        accepted: int,
        review_required: int,
        low_confidence: int,
        risk_count: int,
        issue_count: int,
        used_vision: bool,
    ) -> float:
        score = 2.4
        if used_vision:
            score += 0.5
        if annotation_count:
            score += min(0.9, annotation_count / 30)
            score += min(0.7, accepted / max(annotation_count, 1))
        score -= min(1.0, review_required * 0.08)
        score -= min(0.7, low_confidence * 0.12)
        score -= min(0.8, risk_count * 0.15)
        score -= min(0.8, issue_count * 0.2)
        return max(0.0, min(5.0, score))

    def _feasibility_text(self, feasibility: str, score: float) -> str:
        if feasibility == "high":
            return f"可行性较高，当前证据链能支撑生成初版工序图；质量约 {score:.1f}/5，仍需复核关键尺寸。"
        if feasibility == "medium":
            return f"可行性中等，适合生成评审版流程图；质量约 {score:.1f}/5，不能直接作为投产工艺卡。"
        return f"可行性偏低，当前输入只能生成草案；质量约 {score:.1f}/5，应先补充清晰 PDF、CAD 或人工确认参数。"

    def _summary(self, feasibility: str, operations: list[Any], annotations: list[Any], validation_issues: list[Any]) -> str:
        prefix = {
            "high": "系统已形成从图纸识别到工序流程的闭环",
            "medium": "系统已能形成可读流程草案，但证据需要补强",
            "low": "系统当前更适合做图纸预审和问题清单",
        }[feasibility]
        return f"{prefix}：输出 {len(operations)} 道工序，关联 {len(annotations)} 条结构化标注，发现 {len(validation_issues)} 个流程校验问题。"

    def _readability_text(self, annotations: list[Any], export_rows: list[Any], review_required: int) -> str:
        if not annotations and not export_rows:
            return "当前快速层没有展开精细参数表，前端主要展示工序和风险，保存案例后再做精细标注更合适。"
        if review_required:
            return f"结构化数据已转成可读摘要，但仍有 {review_required} 条标注需要人工复核；前端不应只展示原始 JSON。"
        return "结构化数据可读性较好，可直接展示参数摘要、工序依据和复核结论。"

    def _usable_data(self, annotations: list[Any], export_rows: list[Any], type_counter: Counter) -> list[str]:
        usable: list[str] = []
        trusted = [
            item
            for item in annotations
            if item.confidence >= 0.85 and item.review_status in {"accepted", "pending"}
        ][:8]
        for item in trusted:
            name = item.parameter_name or item.label or item.raw_text or item.annotation_id
            value = item.parameter_value or item.normalized_text or item.raw_text
            usable.append(f"{name}：{value}（置信度 {item.confidence:.2f}）")
        if not usable and export_rows:
            for row in export_rows[:8]:
                usable.append(f"{row.parameter_name}：{row.parameter_value or row.upper_limit or row.lower_limit or '待确认'}")
        if not usable and type_counter:
            usable.append("已识别参数类型：" + "、".join(f"{key} {count} 条" for key, count in type_counter.most_common()))
        return usable

    def _issues(
        self,
        parse_result: DrawingParseResult,
        process_plan: ProcessPlan,
        annotation_result: DrawingAnnotationResult,
        low_confidence: int,
    ) -> list[GuidanceIssue]:
        issues: list[GuidanceIssue] = []
        for flag in parse_result.risk_flags[:6]:
            issues.append(GuidanceIssue(title=flag.field, detail=flag.message, severity=flag.severity))
        for issue in process_plan.validation_issues[:6]:
            issues.append(GuidanceIssue(title=issue.code, detail=issue.message, severity=issue.severity))
        if annotation_result.review_required_count:
            issues.append(GuidanceIssue(title="标注复核", detail=f"{annotation_result.review_required_count} 条标注未达到自动放行条件。", severity="warning"))
        if low_confidence:
            issues.append(GuidanceIssue(title="低置信参数", detail=f"{low_confidence} 条标注置信度低于 0.75。", severity="warning"))
        if not issues:
            issues.append(GuidanceIssue(title="当前结论", detail="未发现阻断流程生成的结构化问题。", severity="info"))
        return issues

    def _manual_review_items(
        self,
        parse_result: DrawingParseResult,
        process_plan: ProcessPlan,
        annotation_result: DrawingAnnotationResult,
    ) -> list[str]:
        items: list[str] = []
        for annotation in annotation_result.annotations:
            if annotation.review_status in {"pending", "needs_manual_review"} or annotation.confidence < 0.75:
                name = annotation.parameter_name or annotation.label or annotation.annotation_id
                reason = annotation.review_reason or "置信度或来源不足"
                items.append(f"{name}：{reason}")
            if len(items) >= 8:
                break
        items.extend(flag.message for flag in parse_result.risk_flags[:4])
        items.extend(issue.message for issue in process_plan.validation_issues[:4])
        return list(dict.fromkeys(item for item in items if item))[:10]


process_guidance_service = ProcessGuidanceService()
