from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

from pydantic import ValidationError

from app.config import settings
from app.models.agent import AgentArtifact, AgentProcessResponse, AgentQuestion, AgentRunTrace
from app.models.annotation import AnnotationExportRow, DrawingAnnotation, DrawingAnnotationResult
from app.models.drawing import DrawingParseResult, FeatureType, RequirementType, RiskFlag
from app.models.flow import FlowEdge, ProcessFlow
from app.models.process import Operation, ProcessMode, ProcessPlan
from app.services.ai_service import AIServiceError, ai_service
from app.services.drawing_parser import DrawingParser
from app.services.flow_builder import FlowBuilder
from app.services.process_generator import ProcessGenerator
from app.services.process_validator import ProcessValidator


class ProcessAgent:
    def __init__(self) -> None:
        self.parser = DrawingParser()
        self.generator = ProcessGenerator()
        self.flow_builder = FlowBuilder()
        self.validator = ProcessValidator()

    async def run_from_file(
        self,
        file_path: str | Path,
        mode: ProcessMode = ProcessMode.STANDARD_8,
    ) -> AgentProcessResponse:
        path = Path(file_path)
        trace = AgentRunTrace(goal=settings.agent_goal)
        trace.stages.append("接收图纸文件")

        parse_result = self.parser.parse_file(path)
        trace.stages.append("本地提取 PDF 文本和基础关键词")
        if parse_result.raw_text:
            trace.artifacts.append(
                AgentArtifact(
                    kind="pdf_text",
                    title="PDF 文本提取结果",
                    content=parse_result.raw_text[: settings.agent_max_pdf_text_chars],
                    confidence=0.5,
                )
            )

        image_payloads = self._extract_images(path, trace)
        fallback_plan = self.generator.generate(parse_result, mode)
        trace.artifacts.append(
            AgentArtifact(
                kind="fallback",
                title="旧规则兜底方案",
                content=fallback_plan.model_dump(mode="json"),
                confidence=0.35,
            )
        )

        if settings.agent_enabled and ai_service.enabled:
            try:
                trace.stages.append("AI Agent 读取图纸页面、标注和文字")
                agent_payload = await ai_service.analyze_drawing_for_process_flow(
                    goal=settings.agent_goal,
                    pdf_text=parse_result.raw_text or "",
                    image_payloads=image_payloads,
                    mode=mode.value,
                    fallback_plan=fallback_plan.model_dump(mode="json"),
                )
                trace.used_ai = True
                trace.used_vision = bool(image_payloads)
                return self._build_agent_response(agent_payload, fallback_plan, parse_result, trace, mode)
            except AIServiceError as exc:
                trace.questions.append(
                    AgentQuestion(
                        field="ai_agent",
                        question="AI Agent 未能完成结构化图纸拆分，是否允许检查模型配置或更换视觉模型？",
                        reason=str(exc),
                        severity="critical",
                    )
                )
            except Exception as exc:
                trace.questions.append(
                    AgentQuestion(
                        field="ai_agent",
                        question="AI Agent 运行异常，是否使用旧规则结果临时确认？",
                        reason=f"{type(exc).__name__}: {exc}",
                        severity="critical",
                    )
                )

        trace.fallback_used = True
        trace.stages.append("回退到旧规则方案")
        fallback_plan.requires_manual_review = True
        fallback_plan.validation_issues = self.validator.validate(parse_result, fallback_plan)
        flow = self.flow_builder.build(fallback_plan)
        return AgentProcessResponse(
            parse_result=parse_result,
            annotation_result=DrawingAnnotationResult(),
            process_plan=fallback_plan,
            flow=flow,
            similar_cases=[],
            ai_suggestions=["当前使用旧规则兜底：结果只适合做临时参考，不应视为真实图纸拆分结果"],
            agent_trace=trace,
        )

    async def run_from_files(
        self,
        file_paths: list[str | Path],
        mode: ProcessMode = ProcessMode.STANDARD_8,
    ) -> AgentProcessResponse:
        trace = AgentRunTrace(goal=f"{settings.agent_goal}，并合并多份分步图纸为工人生产指导流程")
        trace.stages.append(f"接收分步图纸 {len(file_paths)} 份")

        parse_results: list[DrawingParseResult] = []
        image_payloads: list[dict[str, str]] = []

        for index, file_path in enumerate(file_paths, start=1):
            path = Path(file_path)
            started_at = perf_counter()
            print(f"[process] batch local step {index}/{len(file_paths)} start: {path.name}", flush=True)
            if path.suffix.lower() == ".pdf":
                parse_result = DrawingParseResult(
                    raw_text="",
                    risk_flags=[
                        RiskFlag(
                            field="pdf_text",
                            message="批量 PDF 已跳过逐份文本抽取，优先进入 AI 视觉合并分析",
                            severity="info",
                        )
                    ],
                )
            else:
                parse_result = self.parser.parse_file(path)
            parse_results.append(parse_result)
            if not image_payloads:
                image_payloads.extend(self._extract_images(path, trace)[:1])
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            print(f"[process] batch local step {index}/{len(file_paths)} done in {elapsed_ms}ms: {path.name}", flush=True)
            trace.stages.append(f"完成第 {index} 份图纸本地解析：{path.name}")

        if not parse_results:
            fallback_parse = DrawingParseResult(risk_flags=[RiskFlag(field="files", message="未收到可分析的图纸文件", severity="critical")])
            fallback_plan = self.generator.generate(fallback_parse, mode)
            return AgentProcessResponse(
                parse_result=fallback_parse,
                annotation_result=DrawingAnnotationResult(),
                process_plan=fallback_plan,
                flow=self.flow_builder.build(fallback_plan),
                similar_cases=[],
                ai_suggestions=["未收到可分析的图纸文件"],
                agent_trace=trace,
            )

        parse_result = parse_results[0].model_copy(deep=True)
        parse_result.raw_text = "\n\n".join([item.raw_text or "" for item in parse_results if item.raw_text])
        for item in parse_results[1:]:
            parse_result.features.extend(item.features)
            parse_result.tolerances.extend(item.tolerances)
            parse_result.technical_requirements.extend(item.technical_requirements)
            parse_result.inspection_requirements.extend(item.inspection_requirements)
            parse_result.risk_flags.extend(item.risk_flags)

        fallback_plan = self.generator.generate(parse_result, mode)
        trace.artifacts.append(
            AgentArtifact(
                kind="fallback",
                title="批量图纸本地兜底方案",
                content=fallback_plan.model_dump(mode="json"),
                confidence=0.35,
            )
        )

        if settings.agent_enabled and ai_service.enabled:
            try:
                trace.stages.append("AI Agent 合并分析批量图纸")
                print(
                    f"[process] batch ai start: files={len(file_paths)}, images={len(image_payloads[:1])}, text_chars={len(parse_result.raw_text or '')}",
                    flush=True,
                )
                ai_started_at = perf_counter()
                payload = await ai_service.analyze_drawing_for_process_flow(
                    goal=trace.goal,
                    pdf_text=parse_result.raw_text or "",
                    image_payloads=image_payloads[:1],
                    mode=mode.value,
                    fallback_plan=fallback_plan.model_dump(mode="json"),
                )
                elapsed_ms = int((perf_counter() - ai_started_at) * 1000)
                print(f"[process] batch ai done in {elapsed_ms}ms", flush=True)
                trace.used_ai = True
                trace.used_vision = bool(image_payloads)
                return self._build_agent_response(payload, fallback_plan, parse_result, trace, mode)
            except Exception as exc:
                print(f"[process] batch ai failed: {type(exc).__name__}: {exc}", flush=True)
                trace.questions.append(
                    AgentQuestion(
                        field="ai_agent",
                        question="AI Agent 批量合并分析失败，已使用本地规则结果避免继续卡住。",
                        reason=f"{type(exc).__name__}: {exc}",
                        severity="warning",
                    )
                )

        trace.fallback_used = True
        fallback_plan.requires_manual_review = True
        fallback_plan.validation_issues = self.validator.validate(parse_result, fallback_plan)
        flow = self.flow_builder.build(fallback_plan)

        return AgentProcessResponse(
            parse_result=parse_result,
            annotation_result=DrawingAnnotationResult(),
            process_plan=fallback_plan,
            flow=flow,
            similar_cases=[],
            ai_suggestions=["已合并批量图纸；当前使用本地快速结果，避免逐文件 AI 处理卡死"],
            agent_trace=trace,
        )

    async def run_from_text(
        self,
        text: str,
        mode: ProcessMode = ProcessMode.STANDARD_8,
    ) -> AgentProcessResponse:
        trace = AgentRunTrace(goal=settings.agent_goal)
        trace.stages.append("接收图纸文字")
        parse_result = self.parser.parse_text(text)
        fallback_plan = self.generator.generate(parse_result, mode)

        if settings.agent_enabled and ai_service.enabled:
            try:
                trace.stages.append("AI Agent 基于文字拆分流程")
                payload = await ai_service.analyze_drawing_for_process_flow(
                    goal=settings.agent_goal,
                    pdf_text=text,
                    image_payloads=[],
                    mode=mode.value,
                    fallback_plan=fallback_plan.model_dump(mode="json"),
                )
                trace.used_ai = True
                return self._build_agent_response(payload, fallback_plan, parse_result, trace, mode)
            except Exception as exc:
                trace.questions.append(
                    AgentQuestion(
                        field="ai_agent",
                        question="AI Agent 文字拆分失败，是否使用旧规则结果临时确认？",
                        reason=f"{type(exc).__name__}: {exc}",
                        severity="warning",
                    )
                )

        trace.fallback_used = True
        flow = self.flow_builder.build(fallback_plan)
        return AgentProcessResponse(
            parse_result=parse_result,
            annotation_result=DrawingAnnotationResult(),
            process_plan=fallback_plan,
            flow=flow,
            similar_cases=[],
            ai_suggestions=["当前使用旧规则兜底"],
            agent_trace=trace,
        )

    def _extract_images(self, path: Path, trace: AgentRunTrace) -> list[dict[str, str]]:
        if path.suffix.lower() != ".pdf":
            return []
        try:
            page_images = self.parser.extract_pdf_page_images(path, max_images=settings.agent_max_images)
            if page_images:
                trace.stages.append(f"渲染 PDF 整页图像 {len(page_images)} 张")
                trace.artifacts.append(
                    AgentArtifact(
                        kind="pdf_page_image",
                        title="PDF 整页图像",
                        content=[{"name": image["name"], "page": image["page"], "mime_type": image["mime_type"]} for image in page_images],
                        confidence=0.9,
                    )
                )
                return page_images

            images = self.parser.extract_pdf_images(path, max_images=settings.agent_max_images)
        except Exception as exc:
            trace.questions.append(
                AgentQuestion(
                    field="pdf_images",
                    question="PDF 图像提取失败，是否允许检查 PDF 渲染依赖或改用 OCR 服务？",
                    reason=f"{type(exc).__name__}: {exc}",
                    severity="critical",
                )
            )
            return []

        trace.stages.append(f"提取 PDF 内嵌图片 {len(images)} 张")
        trace.artifacts.append(
            AgentArtifact(
                kind="pdf_image",
                title="PDF 内嵌图片",
                content=[{"name": image["name"], "page": image["page"], "mime_type": image["mime_type"]} for image in images],
                confidence=0.8 if images else 0.2,
            )
        )
        return images

    def _build_agent_response(
        self,
        payload: dict[str, Any],
        fallback_plan: ProcessPlan,
        fallback_parse_result: DrawingParseResult,
        trace: AgentRunTrace,
        mode: ProcessMode,
    ) -> AgentProcessResponse:
        parse_result = self._coerce_parse_result(payload.get("parse_result"), fallback_parse_result)
        process_plan = self._coerce_process_plan(payload.get("process_plan"), fallback_plan, mode)
        self._normalize_worker_guidance(process_plan)
        self._append_agent_questions(payload.get("questions"), trace)

        process_plan.validation_issues = self.validator.validate(parse_result, process_plan)
        if trace.questions or parse_result.risk_flags or process_plan.validation_issues:
            process_plan.requires_manual_review = True

        flow = self._build_flow(process_plan, payload.get("flow"))
        annotation_result = self._coerce_annotation_result(payload.get("annotation_result") or payload.get("annotations"))
        trace.artifacts.append(
            AgentArtifact(
                kind="annotation_result",
                title="AI Agent 标注识别结果",
                content=annotation_result.model_dump(mode="json"),
                confidence=0.78 if annotation_result.annotations else 0.35,
            )
        )
        trace.artifacts.append(
            AgentArtifact(
                kind="process_plan",
                title="AI Agent 工序拆分结果",
                content=process_plan.model_dump(mode="json"),
                confidence=0.82,
            )
        )
        trace.artifacts.append(
            AgentArtifact(kind="flow", title="AI Agent 流程图", content=flow.model_dump(mode="json"), confidence=0.82)
        )

        suggestions = [str(item) for item in payload.get("suggestions", []) if item]
        if not suggestions:
            suggestions = ["AI Agent 已基于图纸输入生成流程拆分结果"]

        return AgentProcessResponse(
            parse_result=parse_result,
            annotation_result=annotation_result,
            process_plan=process_plan,
            flow=flow,
            similar_cases=[],
            ai_suggestions=suggestions,
            agent_trace=trace,
        )

    def _coerce_annotation_result(self, value: Any) -> DrawingAnnotationResult:
        if isinstance(value, dict):
            annotations = value.get("annotations", [])
            export_rows = value.get("export_rows", [])
        elif isinstance(value, list):
            annotations = value
            export_rows = []
        else:
            return DrawingAnnotationResult()

        safe_annotations: list[DrawingAnnotation] = []
        for index, item in enumerate(annotations, start=1):
            if not isinstance(item, dict):
                continue
            candidate = dict(item)
            candidate.setdefault("annotation_id", f"A{index:03d}")
            candidate.setdefault("raw_text", candidate.get("normalized_text") or candidate.get("parameter_name") or "")
            candidate["semantic_type"] = self._normalize_semantic_type(candidate.get("semantic_type"))
            candidate["source"] = self._normalize_annotation_source(candidate.get("source"))
            candidate["review_status"] = self._normalize_review_status(candidate.get("review_status"))
            try:
                safe_annotations.append(DrawingAnnotation.model_validate(candidate))
            except ValidationError:
                continue

        safe_rows: list[AnnotationExportRow] = []
        if isinstance(export_rows, list):
            for index, item in enumerate(export_rows, start=1):
                if not isinstance(item, dict):
                    continue
                candidate = dict(item)
                candidate.setdefault("row_no", index)
                candidate.setdefault("annotation_id", f"A{index:03d}")
                candidate.setdefault("parameter_name", candidate.get("raw_text") or candidate.get("annotation_id") or "未命名参数")
                try:
                    safe_rows.append(AnnotationExportRow.model_validate(candidate))
                except ValidationError:
                    continue

        if not safe_rows:
            safe_rows = [
                AnnotationExportRow(
                    row_no=index,
                    annotation_id=annotation.annotation_id,
                    parameter_name=annotation.parameter_name or annotation.normalized_text or annotation.raw_text or annotation.annotation_id,
                    parameter_value=annotation.parameter_value or "",
                    upper_limit=annotation.upper_limit or "",
                    lower_limit=annotation.lower_limit or "",
                    unit=annotation.unit or "",
                    semantic_type=annotation.semantic_type,
                    review_status=annotation.review_status,
                    source=annotation.source,
                    confidence=annotation.confidence,
                )
                for index, annotation in enumerate(safe_annotations, start=1)
            ]

        review_required_count = sum(
            1 for annotation in safe_annotations if annotation.review_status in {"pending", "needs_manual_review"}
        )
        return DrawingAnnotationResult(
            annotations=safe_annotations,
            export_rows=safe_rows,
            bubble_diagram_available=bool(safe_annotations),
            review_required_count=review_required_count,
        )

    def _normalize_semantic_type(self, value: Any) -> str:
        raw = str(value or "unknown").strip().lower()
        alias_map = {
            "size": "dimension",
            "尺寸": "dimension",
            "公差": "tolerance",
            "roughness": "roughness",
            "粗糙度": "roughness",
            "datum": "datum",
            "基准": "datum",
            "gdt": "geometric_tolerance",
            "geometric": "geometric_tolerance",
            "material": "material",
            "note": "process_note",
            "process": "process_note",
            "inspection": "inspection_note",
            "quality": "quality_note",
        }
        normalized = alias_map.get(raw, raw)
        allowed = {
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
        }
        return normalized if normalized in allowed else "unknown"

    def _normalize_annotation_source(self, value: Any) -> str:
        raw = str(value or "agent_reasoning").strip().lower()
        if raw in {"pdf_text", "pdf_page_image", "pdf_embedded_image", "agent_reasoning", "manual"}:
            return raw
        if raw in {"image", "vision", "page_image"}:
            return "pdf_page_image"
        return "agent_reasoning"

    def _normalize_review_status(self, value: Any) -> str:
        raw = str(value or "pending").strip().lower()
        if raw in {"pending", "accepted", "rejected", "needs_manual_review"}:
            return raw
        if raw in {"review", "manual", "warning"}:
            return "needs_manual_review"
        return "pending"

    def _coerce_parse_result(self, value: Any, fallback: DrawingParseResult) -> DrawingParseResult:
        if not isinstance(value, dict):
            fallback.risk_flags.append(RiskFlag(field="agent_parse_result", message="AI 未返回有效图纸解析结果", severity="warning"))
            return fallback
        normalized = self._normalize_parse_result(value)
        try:
            return DrawingParseResult.model_validate(normalized)
        except ValidationError as exc:
            fallback.risk_flags.append(RiskFlag(field="agent_parse_result", message=f"AI 图纸解析结构不兼容：{exc.errors()[0]['msg']}", severity="warning"))
            return fallback

    def _normalize_parse_result(self, value: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(value)
        features = normalized.get("features")
        if isinstance(features, list):
            normalized["features"] = [self._normalize_feature(item) for item in features if isinstance(item, dict)]
        requirements = normalized.get("technical_requirements")
        if isinstance(requirements, list):
            normalized["technical_requirements"] = [
                self._normalize_requirement(item) for item in requirements if isinstance(item, dict)
            ]
        return normalized

    def _normalize_requirement(self, requirement: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(requirement)
        raw_type = str(normalized.get("type") or "unknown").strip().lower()
        allowed_types = {item.value for item in RequirementType}
        alias_map = {
            "dimension": "dimension_requirement",
            "size": "dimension_requirement",
            "尺寸": "dimension_requirement",
            "tolerance": "tolerance_requirement",
            "geometric_tolerance": "tolerance_requirement",
            "公差": "tolerance_requirement",
            "roughness": "roughness_requirement",
            "surface_roughness": "roughness_requirement",
            "粗糙度": "roughness_requirement",
            "material": "material_requirement",
            "材料": "material_requirement",
            "heat": "heat_treatment",
            "thermal_treatment": "heat_treatment",
            "热处理": "heat_treatment",
            "surface": "surface_treatment",
            "coating": "surface_treatment",
            "表面处理": "surface_treatment",
            "machining": "machining_requirement",
            "processing": "machining_requirement",
            "加工要求": "machining_requirement",
            "inspection": "inspection_requirement",
            "testing": "inspection_requirement",
            "检验": "inspection_requirement",
            "quality": "quality_requirement",
            "质量": "quality_requirement",
            "parameter": "process_parameter",
            "process_parameter_requirement": "process_parameter",
            "annotation": "annotation_requirement",
            "note": "annotation_requirement",
            "technical_note": "annotation_requirement",
            "requirement": "general_requirement",
            "technical_requirement": "general_requirement",
            "general": "general_requirement",
        }
        normalized_type = alias_map.get(raw_type, raw_type)
        if normalized_type not in allowed_types:
            normalized["source_text"] = self._append_source_note(normalized.get("source_text"), f"AI原始要求类型：{raw_type}")
            normalized_type = "general_requirement"
        normalized["type"] = normalized_type
        if not normalized.get("content"):
            normalized["content"] = normalized.get("source_text") or raw_type or "未命名技术要求"
        return normalized

    def _normalize_feature(self, feature: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(feature)
        raw_type = str(normalized.get("type") or "unknown").strip().lower()
        allowed_types = {item.value for item in FeatureType}
        alias_map = {
            "bearing": "shaft",
            "journal": "shaft",
            "axis": "shaft",
            "axle": "shaft",
            "cylinder": "shaft",
            "bore": "hole",
            "through_hole": "hole",
            "blind_hole": "hole",
            "screw_hole": "thread",
            "tapped_hole": "thread",
            "internal_thread": "thread",
            "external_thread": "thread",
            "channel": "groove",
            "oil_channel": "oil_hole",
            "edge": "surface",
            "face": "surface",
            "plane": "surface",
            "profile": "general_feature",
            "contour": "general_feature",
            "curve": "general_feature",
            "line": "annotation",
            "text": "annotation",
            "note": "process_note",
            "view": "detail_view",
            "section": "section_view",
            "detail": "detail_view",
        }
        normalized_type = alias_map.get(raw_type, raw_type)
        if normalized_type not in allowed_types:
            normalized["source_text"] = self._append_source_note(normalized.get("source_text"), f"AI原始特征类型：{raw_type}")
            normalized_type = "general_feature"
        normalized["type"] = normalized_type
        if not normalized.get("name"):
            normalized["name"] = raw_type or "未命名图纸特征"
        return normalized

    def _append_source_note(self, source_text: Any, note: str) -> str:
        if isinstance(source_text, str) and source_text.strip():
            return f"{source_text.strip()}；{note}"
        return note

    def _coerce_process_plan(self, value: Any, fallback: ProcessPlan, mode: ProcessMode) -> ProcessPlan:
        if not isinstance(value, dict):
            fallback.requires_manual_review = True
            return fallback
        candidate = dict(value)
        candidate.setdefault("mode", mode.value)
        candidate.setdefault("validation_issues", [])
        try:
            return ProcessPlan.model_validate(candidate)
        except ValidationError:
            fallback.requires_manual_review = True
            return fallback

    def _normalize_worker_guidance(self, process_plan: ProcessPlan) -> None:
        for operation in process_plan.operations:
            if not operation.worker_steps:
                operation.worker_steps = [operation.content]
            if not operation.materials:
                operation.materials = ["按图纸和工艺卡领取零件、毛坯或半成品"]
            if not operation.tools:
                operation.tools = ["按本工序设备和质量要求准备工装、刀具、量具"]
            if not operation.setup_requirements:
                operation.setup_requirements = ["核对图号、工序号、基准和装夹状态后再开始加工"]
            if not operation.safety_points:
                operation.safety_points = ["开机前确认防护、夹紧和人员站位安全"]
            if not operation.quality_gates:
                if operation.inspection_items:
                    operation.quality_gates = [f"确认{item}" for item in operation.inspection_items]
                else:
                    operation.quality_gates = ["本工序完成后自检关键尺寸、表面状态和记录完整性"]
            if not operation.handoff_requirements:
                operation.handoff_requirements = ["交接图纸标注、检测记录、异常项和当前工件状态"]

    def _append_agent_questions(self, value: Any, trace: AgentRunTrace) -> None:
        if not isinstance(value, list):
            return
        for item in value:
            if not isinstance(item, dict):
                continue
            try:
                trace.questions.append(AgentQuestion.model_validate(item))
            except ValidationError:
                continue

    def _build_flow(self, plan: ProcessPlan, value: Any) -> ProcessFlow:
        if not isinstance(value, dict):
            return self.flow_builder.build(plan)
        raw_edges = value.get("edges")
        if not isinstance(raw_edges, list):
            return self.flow_builder.build(plan)

        node_ids_by_no = {operation.operation_no: f"op_{operation.operation_no}" for operation in plan.operations}
        edges: list[FlowEdge] = []
        for item in raw_edges:
            if not isinstance(item, dict):
                continue
            source = node_ids_by_no.get(str(item.get("source_operation_no")))
            target = node_ids_by_no.get(str(item.get("target_operation_no")))
            if source and target:
                edges.append(FlowEdge(source=source, target=target, label=item.get("label")))
        if not edges:
            return self.flow_builder.build(plan)
        return self.flow_builder.build_with_edges(plan, edges)


process_agent = ProcessAgent()