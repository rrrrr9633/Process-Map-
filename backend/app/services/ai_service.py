from __future__ import annotations

import json
import re
from time import perf_counter
from typing import Any

import httpx

from app.config import settings
from app.models.process import ProcessPlan


class AIServiceError(RuntimeError):
    pass


class AIService:
    """AI 大模型服务：Agent 主链负责图纸理解，旧链路只做兼容增强。"""

    def __init__(self):
        self.provider = settings.ai_model_provider
        self.api_key = settings.ai_api_key
        self.api_base = settings.ai_api_base.rstrip("/")
        self.model_name = settings.ai_model_name
        self.timeout_seconds = settings.ai_timeout_seconds
        self.enabled = bool(self.api_key)

    async def analyze_drawing_for_process_flow(
        self,
        *,
        goal: str,
        pdf_text: str,
        image_payloads: list[dict[str, str]],
        mode: str,
        fallback_plan: dict[str, Any],
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
                        "pdf_text": pdf_text[: settings.agent_max_pdf_text_chars],
                        "image_count": len(image_payloads),
                        "fallback_plan": fallback_plan,
                        "output_schema": self._agent_output_schema(),
                        "rules": [
                            "优先根据 PDF 图片中的真实结构、标注、技术要求拆分流程，不要套固定模板。",
                            "如果图片或文字证据不足，必须在 questions 中提出人工确认项。",
                            "工序数量按复杂度动态决定，不强制 8 或 10 道。",
                            "每道工序必须说明 drawing_basis，标明来自图片观察、PDF文字或工艺推理。",
                            "每道工序必须输出 worker_steps、materials、tools、setup_requirements、safety_points、quality_gates、handoff_requirements，保证工人能按步骤生产。",
                            "流程边 edges 必须表达实际先后关系；如有并行、返修、人工确认，也要输出对应关系。",
                            "只返回 JSON，不要返回 Markdown。",
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

        result = await self._chat_completion(payload)
        parsed = self._extract_json(result)
        if not parsed:
            raise AIServiceError(f"AI Agent 返回了非结构化结果：{result.strip()}")
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
                "annotations": [
                    {
                        "annotation_id": "A001",
                        "label": "气泡编号或标注编号",
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
                        "review_reason": "需要审核的原因",
                    }
                ],
                "export_rows": [
                    {
                        "row_no": 1,
                        "annotation_id": "A001",
                        "parameter_name": "参数名",
                        "parameter_value": "参数值",
                        "upper_limit": "上限",
                        "lower_limit": "下限",
                        "unit": "单位",
                        "semantic_type": "dimension",
                        "review_status": "pending",
                        "source": "pdf_page_image",
                        "confidence": 0.8,
                    }
                ],
                "bubble_diagram_available": True,
                "review_required_count": 1,
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

    async def _chat_completion(self, payload: dict[str, Any]) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        stream_payload = dict(payload)
        stream_payload["stream"] = True
        request_started_at = perf_counter()
        print(
            f"[ai] prepare request: provider={self.provider}, model={self.model_name}, timeout={self.timeout_seconds}s, messages={len(payload.get('messages', []))}",
            flush=True,
        )

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            print("[ai] stream request start: json_mode=true", flush=True)
            response = await self._post_stream(client, headers, stream_payload)
            if response is not None:
                elapsed_ms = int((perf_counter() - request_started_at) * 1000)
                print(f"[ai] stream request done in {elapsed_ms}ms, chars={len(response)}", flush=True)
                return response

            if "response_format" in stream_payload:
                fallback_payload = dict(stream_payload)
                fallback_payload.pop("response_format", None)
                print("[ai] stream retry start: json_mode=false", flush=True)
                response = await self._post_stream(client, headers, fallback_payload)
                if response is not None:
                    elapsed_ms = int((perf_counter() - request_started_at) * 1000)
                    print(f"[ai] stream retry done in {elapsed_ms}ms, chars={len(response)}", flush=True)
                    return response

            non_stream_payload = dict(payload)
            non_stream_payload["stream"] = False
            print("[ai] non-stream request start: json_mode=true", flush=True)
            response = await client.post(f"{self.api_base}/chat/completions", headers=headers, json=non_stream_payload)
            if response.status_code in {400, 422} and "response_format" in non_stream_payload:
                non_stream_payload.pop("response_format", None)
                print(f"[ai] non-stream retry start: status={response.status_code}, json_mode=false", flush=True)
                response = await client.post(f"{self.api_base}/chat/completions", headers=headers, json=non_stream_payload)
            self._raise_for_ai_response(response)
            data = response.json()
        content = data["choices"][0]["message"]["content"]
        elapsed_ms = int((perf_counter() - request_started_at) * 1000)
        print(f"[ai] non-stream request done in {elapsed_ms}ms, chars={len(content)}", flush=True)
        return content

    async def _post_stream(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> str | None:
        content_parts: list[str] = []
        chunk_count = 0
        started_at = perf_counter()
        async with client.stream("POST", f"{self.api_base}/chat/completions", headers=headers, json=payload) as response:
            print(f"[ai] stream connected: status={response.status_code}", flush=True)
            if response.status_code >= 400:
                print(f"[ai] stream rejected: status={response.status_code}", flush=True)
                return None
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
                        if chunk_count % 20 == 0:
                            print(f"[ai] streaming content: chunks={chunk_count}, chars={sum(len(part) for part in content_parts)}", flush=True)
        content = "".join(content_parts).strip()
        print(f"[ai] stream closed: chunks={chunk_count}, chars={len(content)}", flush=True)
        return content

    def _raise_for_ai_response(self, response: httpx.Response) -> None:
        detail = self._response_error_detail(response)
        if response.status_code == 502:
            raise AIServiceError(f"AI 服务网关暂时不可用（502），请稍后重试或检查 AI_API_BASE{detail}")
        if response.status_code >= 500:
            raise AIServiceError(f"AI 服务暂时不可用（HTTP {response.status_code}），请稍后重试{detail}")
        if response.status_code >= 400:
            raise AIServiceError(f"AI 请求失败（HTTP {response.status_code}），请检查模型名称、密钥或接口地址{detail}")

    def _response_error_detail(self, response: httpx.Response) -> str:
        text = response.text.strip()
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

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
        return None


ai_service = AIService()