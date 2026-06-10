from __future__ import annotations

import json
import re
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx

from app.config import settings
from app.models.process import ProcessPlan
from app.services.model_profile_service import model_profile_service


class AIServiceError(RuntimeError):
    pass


class AIService:
    """AI 大模型服务：Agent 主链负责图纸理解，旧链路只做兼容增强。"""

    def __init__(self):
        pass

    @property
    def provider(self) -> str:
        return model_profile_service.active_profile().provider

    @property
    def api_key(self) -> str:
        return model_profile_service.active_profile().api_key

    @property
    def api_base(self) -> str:
        return model_profile_service.active_profile().api_base

    @property
    def model_name(self) -> str:
        return model_profile_service.active_profile().model

    @property
    def timeout_seconds(self) -> float:
        return model_profile_service.active_profile().timeout_seconds

    @property
    def enabled(self) -> bool:
        return model_profile_service.active_profile().configured

    def ocr_image_text(self, image_path: Path, *, prompt: str | None = None) -> str:
        """同步调用多模态模型提取图纸文字（供 OCR 链路复用 AI_API_KEY）。"""
        from pathlib import Path as _Path
        import base64

        path = _Path(image_path)
        if not self.enabled or not path.is_file():
            return ""
        try:
            raw = path.read_bytes()
        except Exception:
            return ""
        mime = "image/png"
        if path.suffix.lower() in {".jpg", ".jpeg"}:
            mime = "image/jpeg"
        b64 = base64.b64encode(raw).decode("ascii")
        user_prompt = prompt or "只输出图纸中可见文字与尺寸标注，保持换行，不要解释。"
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": "你是 OCR 助手，只返回识别到的文字。"},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"}},
                    ],
                },
            ],
            "temperature": 0,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                if self._uses_responses_api:
                    response = client.post(
                        f"{self.api_base}/responses",
                        headers=headers,
                        json=self._responses_payload(payload),
                    )
                else:
                    response = client.post(f"{self.api_base}/chat/completions", headers=headers, json=payload)
            if response.status_code >= 400:
                return ""
            data = response.json()
            content = self._response_text(data)
            return str(content).strip()
        except Exception:
            return ""

    async def analyze_drawing_for_process_flow(
        self,
        *,
        goal: str,
        pdf_text: str,
        image_payloads: list[dict[str, str]],
        mode: str,
        target_operation_count: int = 15,
        per_file_explanations: list[dict[str, Any]] | None = None,
        on_stream_delta: Any | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            raise AIServiceError("AI Agent 未启用：未配置 AI_API_KEY")

        user_content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "goal": goal,
                        "mode": mode,
                        "target_operation_count": target_operation_count,
                        "pdf_text": pdf_text[: settings.agent_max_pdf_text_chars],
                        "image_count": len(image_payloads),
                        "per_file_explanations": per_file_explanations or [],
                        "output_schema": self._agent_output_schema(),
                        "rules": [
                            "优先根据 PDF 图片中的真实结构、标注、技术要求拆分流程，不要套固定模板。",
                            "如果图片或文字证据不足，必须在 questions 中提出人工确认项。",
                            f"前台快速生成只输出约 {target_operation_count} 道轻量工序；除非图纸证据强烈，不要大幅偏离该数量。",
                            "优先使用图纸中的 OP 编号；没有 OP 编号时按生产顺序生成 OP05/OP10 等编号。",
                            "每道工序只保留工序编号、工序名称、工序内容、核心参数、质控点和简要图纸依据；不要展开精细标注表。",
                            "worker_steps、materials、tools、setup_requirements、safety_points、quality_gates、handoff_requirements 均保持简短，最多 3 项。",
                            "流程边 edges 必须表达实际先后关系；如有并行、返修、人工确认，也要输出对应关系。",
                            "只返回 JSON，不要返回 Markdown。",
                            "annotation_result 必须返回空 annotations/export_rows；精细注解、气泡图和标注导出只在保存案例后的精细标注后台执行。",
                            "若提供 per_file_explanations，必须结合每份图纸、每页的图解结论拆分流程，并在 drawing_basis 中引用 file_index/page。",
                        ],
                    },
                    ensure_ascii=False,
                ),
            }
        ]
        for image in image_payloads[: settings.agent_max_images]:
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{image['mime_type']};base64,{image['base64']}",
                        "detail": "high",
                    },
                }
            )

        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是机械图纸工艺流程拆分 Agent。你的任务是观察 PDF 图纸图片和文字，"
                        "抽取零件结构、尺寸/公差/粗糙度、加工/检验/清洗/特殊处理要求，"
                        "再生成可执行的流程图数据。不要简单润色模板，必须输出严格 JSON。"
                    ),
                },
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }

        result = await self._chat_completion(payload, on_stream_delta=on_stream_delta)
        parsed = self._extract_json(result)
        if not parsed:
            preview = result.strip().replace("\n", " ")[:300]
            raise AIServiceError(f"AI Agent JSON 未完整返回或无法解析，已截断预览：{preview}")
        return parsed

    async def explain_single_drawing_page(
        self,
        *,
        file_name: str,
        file_index: int,
        page: int = 1,
        page_count: int = 1,
        image_payload: dict[str, str],
        ocr_text: str = "",
        view_label: str = "",
        view_region: dict[str, float] | None = None,
        on_stream_delta: Any | None = None,
        simplified: bool = False,
    ) -> dict[str, Any]:
        if not self.enabled:
            raise AIServiceError("AI Agent 未启用：未配置 AI_API_KEY")

        max_annotations = 5 if simplified else 12
        output_schema = {
            "visual_summary": "这张图纸主要表达的零件、加工步骤或检验内容，必须是工人能听懂的话，120字以内",
            "detected_features": [f"最多{4 if simplified else 8}个关键结构、加工对象、关键区域"],
            "related_operations": ["最多3个建议对应的工序名称或编号"],
            "risk_notes": ["最多5个需要人工确认的疑点，说明为什么影响工艺"],
            "annotation_result": {
                "annotations": [
                    {
                        "annotation_id": "A001",
                        "label": "标注短名",
                        "region": {"page": 1, "x": 0.1, "y": 0.2, "width": 0.08, "height": 0.04, "unit": "ratio"},
                        "raw_text": "图纸原始标注内容",
                        "normalized_text": "归一化标注内容",
                        "parameter_name": "参数名",
                        "parameter_value": "参数值",
                        "upper_limit": "上限",
                        "lower_limit": "下限",
                        "unit": "单位",
                        "semantic_type": "dimension|tolerance|roughness|datum|geometric_tolerance|material|process_note|inspection_note|quality_note|unknown",
                        "source": "pdf_page_image|pdf_embedded_image|pdf_text|agent_reasoning",
                        "confidence": 0.8,
                        "review_status": "pending|accepted|rejected|needs_manual_review",
                        "review_reason": "审核原因，必须说明是看不清、符号不确定、坐标不准、还是推理来源",
                    }
                ],
                "export_rows": [],
                "bubble_diagram_available": False,
                "review_required_count": 0,
            },
        }
        user_content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "file_name": file_name,
                        "file_index": file_index,
                        "page": page,
                        "page_count": page_count,
                        "view_label": view_label,
                        "view_region": view_region or {},
                        "ocr_text": ocr_text[:1500 if simplified else 4000],
                        "goal": "解释单张 PDF 图纸页面或其中一个视图，提取标注并为气泡图生成提供坐标依据",
                        "output_schema": output_schema,
                        "rules": [
                            "只返回 JSON，不要返回 Markdown。",
                            "visual_summary 必须用工人能理解的话说明这张图在表达什么，不要使用只有软件工程师才懂的字段名。",
                            f"detected_features 最多 {4 if simplified else 8} 项，related_operations 最多 3 项，risk_notes 最多 5 项。",
                            f"annotations 最多 {max_annotations} 项，按优先级提取：基准/形位公差、关键尺寸公差、粗糙度、热处理/动平衡/检验要求、螺纹/孔/圆角/倒角。",
                            "不要直接生成气泡图或图片；只输出结构化 JSON，气泡图由后端用标注列表生成。",
                            "每条 annotation 的 parameter_name 必须是中文工程名称；parameter_value 使用显示安全写法：Ra 写 Ra，粗糙度图形符号省略，Ø/∅ 统一写 Φ，± 写 ±，× 写 ×，° 写 °。",
                            "不要输出容易渲染成方块的形位/粗糙度 Unicode 符号；形位公差符号用中文描述，例如 ⊥ 写 垂直度，∥ 写 平行度。",
                            "annotations 中 region 坐标使用 unit=ratio；若提供了 view_region 则相对当前视图裁剪图 0~1，否则相对整页 0~1；无法确定坐标时只在 risk_notes 说明，不要额外创建 annotation。",
                            "结合 ocr_text 校正尺寸和标注，不要与 OCR 明显冲突。",
                            "不要编造具体尺寸、公差或材料；看不清就放入 risk_notes。",
                            "如果标注内容清楚但坐标不确定，可以返回 annotation，但 review_status 必须是 needs_manual_review，review_reason 写明坐标需人工校正。",
                            "返回结果要服务于后续生成工序图：优先保留会影响加工、检验、装夹、清洗、动平衡、打刻的标注。",
                        ],
                    },
                    ensure_ascii=False,
                ),
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{image_payload['mime_type']};base64,{image_payload['base64']}",
                        "detail": "low" if simplified else "high",
                },
            },
        ]
        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是机械图纸图解 Agent。你只分析当前这一张图纸页面，输出严格 JSON。"
                        if not simplified
                        else "你是机械图纸图解 Agent。当前为降级重试，只输出简短、合法 JSON。"
                    ),
                },
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        result = await self._chat_completion(payload, on_stream_delta=on_stream_delta, disable_timeout=True)
        parsed = self._extract_json(result)
        if not parsed:
            preview = result.strip().replace("\n", " ")[:300]
            raise AIServiceError(f"AI 单图图解 JSON 未完整返回或无法解析，已截断预览：{preview}")
        return parsed

    async def enhance_process_plan(self, process_plan: ProcessPlan, drawing_info: dict[str, Any]) -> tuple[ProcessPlan, list[str]]:
        if not self.enabled:
            return process_plan, ["AI增强未启用：未配置 AI_API_KEY"]

        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是一位机械制造工艺工程师。请在不改变工序编号、不删除强制工序的前提下，"
                        "根据图纸解析信息增强曲轴工序方案。只返回 JSON，不要返回 Markdown。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "drawing_info": drawing_info,
                            "process_plan": process_plan.model_dump(mode="json"),
                            "output_schema": {
                                "operations": [
                                    {
                                        "operation_no": "原工序编号",
                                        "content": "增强后的工序内容",
                                        "worker_steps": ["工人按顺序执行的操作步骤"],
                                        "materials": ["零件、原料、辅料"],
                                        "tools": ["工装、刀具、量具、辅助工具"],
                                        "setup_requirements": ["装夹、设备准备、基准确认"],
                                        "safety_points": ["安全注意事项"],
                                        "quality_gates": ["本工序放行前必须满足的质量条件"],
                                        "handoff_requirements": ["交给下一工序前需要同步的记录和状态"],
                                        "control_points": ["控制点"],
                                        "equipment": ["设备"],
                                        "inspection_items": ["检验项"],
                                        "ai_note": "该工序增强原因",
                                    }
                                ],
                                "suggestions": ["整体建议"],
                            },
                            "requirements": [
                                "必须保持原工序数量和顺序",
                                "必须保留原有控制点，只能补充或优化表达",
                                "不要编造图纸中不存在的关键尺寸或具体公差",
                                "如果图纸信息不足，请给出人工确认建议",
                            ],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }

        result = await self._chat_completion(payload)
        enhanced = self._extract_json(result)
        if not enhanced:
            return process_plan, [f"AI已返回建议，但不是结构化 JSON，未自动改写工序：{result.strip()}"]

        suggestions = [str(item) for item in enhanced.get("suggestions", []) if item]
        operations_by_no = {
            str(item.get("operation_no")): item
            for item in enhanced.get("operations", [])
            if isinstance(item, dict) and item.get("operation_no")
        }

        for operation in process_plan.operations:
            ai_operation = operations_by_no.get(operation.operation_no)
            if not ai_operation:
                continue

            content = ai_operation.get("content")
            if isinstance(content, str) and content.strip():
                operation.content = content.strip()

            for field_name in (
                "worker_steps",
                "materials",
                "tools",
                "setup_requirements",
                "safety_points",
                "quality_gates",
                "handoff_requirements",
                "control_points",
                "equipment",
                "inspection_items",
            ):
                values = ai_operation.get(field_name)
                if isinstance(values, list):
                    current_values = getattr(operation, field_name)
                    for value in values:
                        text = str(value).strip()
                        if text and text not in current_values:
                            current_values.append(text)

            ai_note = ai_operation.get("ai_note")
            if isinstance(ai_note, str) and ai_note.strip():
                operation.triggered_by.append("ai_enhancement")
                operation.drawing_basis.append(f"AI增强：{ai_note.strip()}")

        if not suggestions:
            suggestions.append("AI增强已应用到工序内容和控制点")
        return process_plan, suggestions

    def _agent_output_schema(self) -> dict[str, Any]:
        return {
            "parse_result": {
                "part": {"part_name": "零件名称", "drawing_no": "图号", "material": "材料", "blank_type": "毛坯", "heat_treatment": "热处理"},
                "features": [{"type": "shaft|hole|thread|slot|groove|keyway|surface|datum|dimension|tolerance|annotation|section_view|detail_view|assembly_relation|process_note|general_feature|unknown", "name": "结构名称", "description": "结构描述", "location": "位置", "source_text": "证据", "confidence": "high|medium|low"}],
                "tolerances": [{"name": "尺寸/形位/粗糙度对象", "nominal": "名义值", "tolerance": "公差", "geometric_tolerance": "形位公差", "roughness": "粗糙度", "source_text": "证据", "confidence": "high|medium|low"}],
                "technical_requirements": [{"type": "dimension_requirement|tolerance_requirement|roughness_requirement|material_requirement|heat_treatment|surface_treatment|machining_requirement|inspection_requirement|quality_requirement|process_parameter|annotation_requirement|general_requirement|unknown", "content": "技术要求", "source_text": "证据", "confidence": "high|medium|low"}],
                "inspection_requirements": [{"item": "检验项", "method": "方法", "acceptance": "验收要求", "source_text": "证据", "confidence": "high|medium|low"}],
                "risk_flags": [{"field": "字段", "message": "风险", "severity": "info|warning|critical"}],
                "raw_text": "关键原文或图片观察摘要",
            },
            "annotation_result": {
                "annotations": [],
                "export_rows": [],
                "bubble_diagram_available": False,
                "review_required_count": 0,
            },
            "process_plan": {
                "title": "流程标题",
                "operations": [
                    {
                        "operation_no": "01",
                        "operation_name": "工序名称",
                        "operation_type": "blank_preparation|baseline_processing|rough_machining|semi_finishing|hole_processing|finishing|inspection|special_process|cleaning_final_inspection",
                        "targets": ["加工对象"],
                        "content": "工序内容",
                        "worker_steps": ["工人按顺序执行的操作步骤"],
                        "materials": ["零件、原料、辅料"],
                        "tools": ["工装、刀具、量具、辅助工具"],
                        "setup_requirements": ["装夹、设备准备、基准确认"],
                        "safety_points": ["安全注意事项"],
                        "quality_gates": ["本工序放行前必须满足的质量条件"],
                        "handoff_requirements": ["交给下一工序前需要同步的记录和状态"],
                        "control_points": ["控制点"],
                        "equipment": ["设备"],
                        "inspection_items": ["检验项"],
                        "drawing_basis": ["图纸依据/图片观察依据"],
                        "mandatory": True,
                        "requires_manual_review": False,
                        "triggered_by": ["pdf_image", "pdf_text", "agent_reasoning"],
                    }
                ],
                "requires_manual_review": False,
            },
            "flow": {"edges": [{"source_operation_no": "01", "target_operation_no": "02", "label": "先后关系"}]},
            "suggestions": ["建议"],
            "questions": [{"field": "缺失字段", "question": "需要用户确认的问题", "reason": "原因", "severity": "warning"}],
        }

    async def _chat_completion(
        self,
        payload: dict[str, Any],
        on_stream_delta: Any | None = None,
        timeout_seconds: float | None = None,
        disable_timeout: bool = False,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        stream_payload = dict(payload)
        stream_payload["stream"] = True
        request_started_at = perf_counter()
        request_timeout = None if disable_timeout else (timeout_seconds if timeout_seconds is not None else self.timeout_seconds)
        timeout_label = "disabled" if request_timeout is None else f"{request_timeout}s"
        print(
            f"[ai] prepare request: provider={self.provider}, model={self.model_name}, timeout={timeout_label}, messages={len(payload.get('messages', []))}",
            flush=True,
        )

        if self._uses_responses_api:
            return await self._responses_completion(
                payload,
                on_stream_delta=on_stream_delta,
                request_timeout=request_timeout,
                request_started_at=request_started_at,
            )

        async with httpx.AsyncClient(timeout=request_timeout) as client:
            print("[ai] stream request start: json_mode=true", flush=True)
            response = await self._post_stream(client, headers, stream_payload, on_stream_delta=on_stream_delta)
            if response is not None:
                elapsed_ms = int((perf_counter() - request_started_at) * 1000)
                print(f"[ai] stream request done in {elapsed_ms}ms, chars={len(response)}", flush=True)
                return response

            if "response_format" in stream_payload:
                fallback_payload = dict(stream_payload)
                fallback_payload.pop("response_format", None)
                print("[ai] stream retry start: json_mode=false", flush=True)
                response = await self._post_stream(client, headers, fallback_payload, on_stream_delta=on_stream_delta)
                if response is not None:
                    elapsed_ms = int((perf_counter() - request_started_at) * 1000)
                    print(f"[ai] stream retry done in {elapsed_ms}ms, chars={len(response)}", flush=True)
                    return response

            raise AIServiceError("AI 流式请求没有返回内容；已停止降级为非流式长时间等待")

    @property
    def _uses_responses_api(self) -> bool:
        return self.provider in {"ark_responses", "responses"}

    async def _responses_completion(
        self,
        payload: dict[str, Any],
        *,
        on_stream_delta: Any | None,
        request_timeout: float | None,
        request_started_at: float,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        response_payload = self._responses_payload(payload)
        async with httpx.AsyncClient(timeout=request_timeout) as client:
            print("[ai] responses request start", flush=True)
            response = await client.post(f"{self.api_base}/responses", headers=headers, json=response_payload)
        if response.status_code >= 400:
            self._raise_for_ai_response_sync(response)
        content = self._response_text(response.json()).strip()
        if on_stream_delta and content:
            try:
                on_stream_delta(content, 1, content)
            except Exception as exc:
                print(f"[ai] responses callback failed: {type(exc).__name__}: {exc}", flush=True)
        elapsed_ms = int((perf_counter() - request_started_at) * 1000)
        print(f"[ai] responses request done in {elapsed_ms}ms, chars={len(content)}", flush=True)
        if not content:
            raise AIServiceError("AI Responses 请求没有返回文本内容")
        return content

    def _responses_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        instructions: list[str] = []
        input_messages: list[dict[str, Any]] = []
        for message in payload.get("messages", []):
            role = message.get("role", "user")
            content = message.get("content", "")
            if role == "system":
                instructions.append(self._message_content_to_text(content))
                continue
            input_messages.append(
                {
                    "role": role,
                    "content": self._responses_content(content),
                }
            )

        response_payload: dict[str, Any] = {
            "model": payload.get("model") or self.model_name,
            "input": input_messages,
        }
        if instructions:
            response_payload["instructions"] = "\n".join(item for item in instructions if item)
        if "temperature" in payload:
            response_payload["temperature"] = payload["temperature"]
        return response_payload

    def _responses_content(self, content: Any) -> list[dict[str, Any]]:
        if isinstance(content, str):
            return [{"type": "input_text", "text": content}]
        if not isinstance(content, list):
            return [{"type": "input_text", "text": json.dumps(content, ensure_ascii=False)}]

        converted: list[dict[str, Any]] = []
        for part in content:
            if not isinstance(part, dict):
                converted.append({"type": "input_text", "text": str(part)})
                continue
            part_type = part.get("type")
            if part_type == "text":
                converted.append({"type": "input_text", "text": str(part.get("text", ""))})
            elif part_type == "image_url":
                image_url = part.get("image_url") or {}
                url = image_url.get("url") if isinstance(image_url, dict) else image_url
                if url:
                    converted.append({"type": "input_image", "image_url": str(url)})
            else:
                converted.append({"type": "input_text", "text": json.dumps(part, ensure_ascii=False)})
        return converted or [{"type": "input_text", "text": ""}]

    def _message_content_to_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    texts.append(str(part.get("text", "")))
            return "\n".join(texts)
        return json.dumps(content, ensure_ascii=False)

    def _response_text(self, data: dict[str, Any]) -> str:
        if data.get("output_text"):
            return str(data["output_text"])
        output_parts: list[str] = []
        for item in data.get("output", []) or []:
            for content in item.get("content", []) or []:
                if isinstance(content, dict):
                    text = content.get("text") or content.get("output_text")
                    if text:
                        output_parts.append(str(text))
        if output_parts:
            return "".join(output_parts)
        return str((((data.get("choices") or [{}])[0].get("message") or {}).get("content")) or "")

    async def _post_stream(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        payload: dict[str, Any],
        on_stream_delta: Any | None = None,
    ) -> str | None:
        content_parts: list[str] = []
        chunk_count = 0
        started_at = perf_counter()
        async with client.stream("POST", f"{self.api_base}/chat/completions", headers=headers, json=payload) as response:
            print(f"[ai] stream connected: status={response.status_code}", flush=True)
            if response.status_code >= 400:
                print(f"[ai] stream rejected: status={response.status_code}", flush=True)
                detail = await self._stream_error_detail(response)
                self._raise_ai_status_error(response.status_code, detail)
            async for line in response.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data:"):
                    continue
                data_text = line.removeprefix("data:").strip()
                if data_text == "[DONE]":
                    elapsed_ms = int((perf_counter() - started_at) * 1000)
                    print(f"[ai] stream done marker received in {elapsed_ms}ms, chunks={chunk_count}", flush=True)
                    break
                try:
                    chunk = json.loads(data_text)
                except json.JSONDecodeError:
                    continue
                for choice in chunk.get("choices", []):
                    delta = choice.get("delta") or {}
                    content = delta.get("content")
                    if content:
                        if not content_parts:
                            elapsed_ms = int((perf_counter() - started_at) * 1000)
                            print(f"[ai] first content chunk received in {elapsed_ms}ms", flush=True)
                        chunk_count += 1
                        content_parts.append(str(content))
                        if on_stream_delta:
                            try:
                                on_stream_delta(str(content), chunk_count, "".join(content_parts))
                            except Exception as exc:
                                print(f"[ai] stream callback failed: {type(exc).__name__}: {exc}", flush=True)
                        if chunk_count % 20 == 0:
                            print(f"[ai] streaming content: chunks={chunk_count}, chars={sum(len(part) for part in content_parts)}", flush=True)
        content = "".join(content_parts).strip()
        print(f"[ai] stream closed: chunks={chunk_count}, chars={len(content)}", flush=True)
        return content

    def _raise_ai_status_error(self, status_code: int, detail: str = "") -> None:
        if status_code == 502:
            raise AIServiceError(f"AI 服务网关暂时不可用（502），请稍后重试或检查 AI_API_BASE{detail}")
        if status_code == 504:
            raise AIServiceError(f"AI 服务网关超时（504），模型没有在网关时限内返回首段内容{detail}")
        if status_code >= 500:
            raise AIServiceError(f"AI 服务暂时不可用（HTTP {status_code}），请稍后重试{detail}")
        if status_code >= 400:
            raise AIServiceError(f"AI 请求失败（HTTP {status_code}），请检查模型名称、密钥或接口地址{detail}")

    async def _stream_error_detail(self, response: httpx.Response) -> str:
        try:
            body = await response.aread()
        except Exception as exc:
            return f"；错误体读取失败：{type(exc).__name__}: {exc}"
        return self._format_error_detail(body)

    async def _raise_for_ai_response(self, response: httpx.Response) -> None:
        detail = self._format_error_detail(response.content)
        self._raise_ai_status_error(response.status_code, detail)

    def _raise_for_ai_response_sync(self, response: httpx.Response) -> None:
        detail = self._format_error_detail(response.content)
        self._raise_ai_status_error(response.status_code, detail)

    def _format_error_detail(self, body: bytes) -> str:
        text = body.decode("utf-8", errors="replace").strip()
        if not text:
            return ""
        compact = " ".join(text.split())
        return f"；接口返回：{compact[:300]}"

    def _extract_json(self, text: str) -> dict[str, Any] | None:
        candidates = [text.strip()]
        fenced_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        candidates.extend(block.strip() for block in fenced_blocks if block.strip())

        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            candidates.append(text[start:end + 1])
        if start >= 0:
            repaired = self._repair_truncated_json(text[start:])
            if repaired:
                candidates.append(repaired)

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
        return None

    def _repair_truncated_json(self, text: str) -> str | None:
        if not text.strip().startswith("{"):
            return None
        result: list[str] = []
        stack: list[str] = []
        in_string = False
        escape = False
        for char in text.strip():
            result.append(char)
            if escape:
                escape = False
                continue
            if char == "\\" and in_string:
                escape = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "{":
                stack.append("}")
            elif char == "[":
                stack.append("]")
            elif char in {"}", "]"} and stack and stack[-1] == char:
                stack.pop()
        if in_string:
            result.append('"')
        repaired = "".join(result).rstrip()
        repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
        while stack:
            closer = stack.pop()
            repaired = re.sub(r",\s*$", "", repaired)
            repaired += closer
        return repaired


ai_service = AIService()
