from __future__ import annotations

from typing import Any

from app.agent_runtime.executor import ControlledAgentExecutor
from app.agent_runtime.state import AgentRun, AgentRunStatus
from app.services.ai_service import AIServiceError, ai_service


class ResponseModule:
    def __init__(self, executor: ControlledAgentExecutor | None = None) -> None:
        self.executor = executor or ControlledAgentExecutor()

    def complete(self, run: AgentRun, final_result: dict[str, Any]) -> AgentRun:
        return self.executor.complete_run(run, final_result)

    def fallback_result(self, run: AgentRun) -> dict[str, Any]:
        return {
            "status": run.status.value,
            "summary": self._summarize_run_outputs(run) or "Agent 运行已停止，等待人工处理或下一轮用户输入。",
            "observations": [item.model_dump(mode="json") for item in run.observations[-3:]],
            "questions": run.questions[-8:],
            "risks": run.risks[-8:],
        }

    async def to_chat_response(self, run: AgentRun, *, user_message: str = "", conversation: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        last_observation = run.observations[-1] if run.observations else None
        final_result = run.final_result or {}
        cards = self._cards(run, final_result)
        business_cards = self._business_cards(run, final_result)
        assistant_message = self._assistant_message(run, final_result)
        actions = self._next_actions(run)
        rendered_reply = await self._compose_rendered_reply(
            run,
            final_result,
            assistant_message,
            business_cards,
            user_message=user_message,
            conversation=conversation or [],
        )
        return {
            "run": run.model_dump(mode="json"),
            "assistant_message": rendered_reply.get("assistant_message") or assistant_message,
            "status": run.status.value,
            "cards": cards,
            "business_cards": business_cards,
            "actions": actions,
            "highlights": rendered_reply.get("highlights") or self._highlights(run, final_result),
            "suggested_replies": self._suggested_replies(rendered_reply, business_cards, run),
            "reply_meta": rendered_reply,
            "tool_trace": [
                {
                    "tool_name": call.tool_name,
                    "arguments": call.arguments,
                    "ok": observation.ok if index < len(run.observations) else None,
                    "elapsed_ms": observation.elapsed_ms if index < len(run.observations) else 0,
                }
                for index, call in enumerate(run.tool_calls)
                for observation in [run.observations[index] if index < len(run.observations) else None]
            ],
            "last_observation": last_observation.model_dump(mode="json") if last_observation else None,
        }

    def _assistant_message(self, run: AgentRun, final_result: dict[str, Any]) -> str:
        if final_result.get("assistant_message"):
            return str(final_result["assistant_message"])
        if run.status == AgentRunStatus.COMPLETED:
            if final_result:
                summary = final_result.get("summary") or final_result.get("answer") or final_result.get("message")
                if summary:
                    return str(summary)
            output_summary = self._summarize_run_outputs(run)
            if output_summary:
                return output_summary
            return "已完成本轮 Agent 分析。"
        if run.status == AgentRunStatus.WAITING_HUMAN:
            pending_call = self._pending_call(run)
            tool_name = pending_call.get("tool_name") or run.current_step or "下一步工具"
            if pending_call:
                return f"我已经规划好下一步，需要你确认后执行工具：{tool_name}。确认后我会继续处理。"
            if run.observations:
                observation = run.observations[-1]
                if observation.requires_human_review:
                    return (
                        f"我已完成工具调用：{observation.tool_name}。结果包含需要人工复核的风险项，"
                        "请查看下方详情；你可以补充要求让我继续分析，或切换到固定分析流程。"
                    )
            if run.questions:
                return "我还需要你补充信息：" + "；".join(run.questions[-3:])
            return "当前结果需要人工确认后继续。"
        if run.status == AgentRunStatus.FAILED:
            event_message = run.events[-1].message if run.events else "Agent 运行失败。"
            return event_message
        if run.observations:
            observation = run.observations[-1]
            if observation.ok:
                output_summary = self._summarize_run_outputs(run)
                if output_summary:
                    return output_summary
                return f"我已完成工具调用：{observation.tool_name}。结果已整理在下方详情中，你可以继续追问或让我进入下一步。"
            return f"工具 {observation.tool_name} 执行失败：{observation.error_message or '未返回可用结果'}"
        return "Agent 已接收任务，正在等待下一步。"

    def _next_actions(self, run: AgentRun) -> list[dict[str, Any]]:
        if run.status == AgentRunStatus.WAITING_HUMAN:
            pending_call = self._pending_call(run)
            if not pending_call:
                return [
                    {"type": "ask_followup", "label": "继续追问"},
                    {"type": "revise_request", "label": "补充需求"},
                ]
            tool_name = pending_call.get("tool_name") or run.current_step or ""
            label = self._tool_confirmation_label(tool_name)
            return [
                {
                    "type": "confirm_tool",
                    "label": label,
                    "tool_name": tool_name,
                    "arguments": pending_call.get("arguments", {}),
                    "requires_human_confirmation": True,
                },
                {"type": "revise_request", "label": "修改需求"},
            ]
        if run.status == AgentRunStatus.COMPLETED:
            return [{"type": "ask_followup", "label": "继续追问"}]
        if run.status == AgentRunStatus.FAILED:
            return [{"type": "retry", "label": "调整后重试"}]
        return []

    def _suggested_replies(
        self,
        rendered_reply: dict[str, Any],
        business_cards: list[dict[str, Any]],
        run: AgentRun,
    ) -> list[str]:
        suggestions: list[str] = []
        followups = rendered_reply.get("followup_questions")
        if isinstance(followups, list):
            suggestions.extend(str(item) for item in followups if item)
        for card in business_cards:
            if card.get("kind") == "next_steps" and isinstance(card.get("items"), list):
                suggestions.extend(str(item) for item in card["items"] if item)
        if run.status == AgentRunStatus.COMPLETED:
            suggestions.extend(
                [
                    "解释一下工序顺序为什么这样安排",
                    "列出需要人工复核的风险点",
                    "下一步可以导出什么结果",
                ]
            )
        return list(dict.fromkeys(item.strip() for item in suggestions if item and item.strip()))[:5]

    async def _compose_rendered_reply(
        self,
        run: AgentRun,
        final_result: dict[str, Any],
        fallback_message: str,
        business_cards: list[dict[str, Any]],
        *,
        user_message: str = "",
        conversation: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        run_summary = {
            "status": run.status.value,
            "summary": fallback_message,
            "questions": run.questions[-8:],
            "risks": run.risks[-8:],
            "final_result": final_result,
            "last_observation": run.observations[-1].model_dump(mode="json") if run.observations else None,
        }
        recent_conversation = conversation or []
        try:
            if ai_service.enabled and (run.final_result or run.observations or user_message):
                rendered = await ai_service.compose_agent_reply(
                    user_message=user_message or run.goal,
                    run_summary=run_summary,
                    business_cards=business_cards,
                    conversation=recent_conversation,
                )
                return rendered if isinstance(rendered, dict) else {"assistant_message": fallback_message}
        except AIServiceError:
            pass
        except Exception:
            pass
        return {"assistant_message": fallback_message}

    def _pending_call(self, run: AgentRun) -> dict[str, Any]:
        for event in reversed(run.events):
            pending_call = event.payload.get("pending_call") if isinstance(event.payload, dict) else None
            if isinstance(pending_call, dict):
                return pending_call
        return {}

    def _tool_confirmation_label(self, tool_name: str) -> str:
        labels = {
            "save_case": "确认保存案例",
            "update_case_status": "确认更新案例状态",
            "add_case_human_edit": "确认记录人工修改",
            "mark_case_ai_error": "确认标记 AI 问题",
            "archive_process_plan_markdown": "确认导出工序说明",
            "export_annotations": "确认导出标注文件",
            "render_process_drawing_assets": "确认生成工艺图文件",
        }
        return labels.get(tool_name, "确认继续执行")

    def _cards(self, run: AgentRun, final_result: dict[str, Any]) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        if final_result:
            cards.append(
                {
                    "kind": "summary",
                    "title": "本轮结论",
                    "content": {
                        "message": final_result.get("summary") or final_result.get("message") or "",
                        "assistant_message": final_result.get("assistant_message") or "",
                    },
                }
            )
        if run.risks:
            cards.append({"kind": "risks", "title": "需要复核的点", "items": run.risks[-6:]})
        if run.questions:
            cards.append({"kind": "questions", "title": "还需要确认", "items": run.questions[-6:]})
        if run.plan:
            cards.append({"kind": "plan", "title": "Agent 计划", "items": run.plan[-6:]})
        if run.observations:
            observation = run.observations[-1]
            cards.append(
                {
                    "kind": "tool_summary",
                    "title": f"最近工具：{observation.tool_name}",
                    "ok": observation.ok,
                    "content": self._summarize_observation(observation.output or {}),
                }
            )
        cards.append(
            {
                "kind": "technical",
                "title": "技术详情",
                "content": {
                    "run": run.model_dump(mode="json"),
                    "final_result": final_result,
                },
            }
        )
        return cards

    def _business_cards(self, run: AgentRun, final_result: dict[str, Any]) -> list[dict[str, Any]]:
        latest = self._latest_outputs(run)
        cards: list[dict[str, Any]] = []
        drawing = self._drawing_summary(latest.get("parse_result"))
        if drawing:
            cards.append({"kind": "drawing_summary", "title": "图纸识别摘要", "content": drawing})
        operations = self._operation_cards(latest.get("process_plan"))
        if operations:
            cards.append({"kind": "process_operations", "title": "工序方案", "items": operations})
        issues = self._validation_issue_cards(latest.get("validation_issues"))
        if issues:
            cards.append({"kind": "validation_issues", "title": "校验与风险", "items": issues})
        next_steps = self._next_step_suggestions(run, latest, final_result)
        if next_steps:
            cards.append({"kind": "next_steps", "title": "下一步建议", "items": next_steps})
        return cards

    def _highlights(self, run: AgentRun, final_result: dict[str, Any]) -> list[str]:
        highlights: list[str] = []
        summary = final_result.get("summary") or ""
        if summary:
            highlights.append(str(summary))
        summary_text = self._summarize_run_outputs(run)
        if summary_text:
            highlights.append(summary_text)
        if run.questions:
            highlights.append("需要确认：" + "；".join(run.questions[-3:]))
        if run.risks:
            highlights.append("需要复核：" + "；".join(run.risks[-3:]))
        return highlights[:4]

    def _summarize_run_outputs(self, run: AgentRun) -> str:
        latest = self._latest_outputs(run)
        parts: list[str] = []
        parse_result = latest.get("parse_result") if isinstance(latest.get("parse_result"), dict) else {}
        process_plan = latest.get("process_plan") if isinstance(latest.get("process_plan"), dict) else {}
        validation_issues = latest.get("validation_issues")

        if parse_result:
            part = parse_result.get("part") if isinstance(parse_result.get("part"), dict) else {}
            part_name = part.get("name") or part.get("part_name") or ""
            risk_flags = parse_result.get("risk_flags") if isinstance(parse_result.get("risk_flags"), list) else []
            if part_name:
                parts.append(f"已解析图纸，识别零件：{part_name}。")
            else:
                parts.append("已完成图纸结构化解析。")
            if risk_flags:
                parts.append(f"解析结果包含 {len(risk_flags)} 项需要复核的风险。")

        if process_plan:
            operations = process_plan.get("operations") if isinstance(process_plan.get("operations"), list) else []
            parts.append(f"已生成规则工序方案，共 {len(operations)} 道工序。")

        if latest.get("process_guidance") and isinstance(latest.get("process_guidance"), dict):
            parts.append("已生成面向工艺人员的指导。")

        if latest.get("final_guidance") and isinstance(latest.get("final_guidance"), dict):
            parts.append("已汇总最终指导结果。")

        if latest.get("process_drawing_plan") and isinstance(latest.get("process_drawing_plan"), dict):
            parts.append("已生成工艺图计划。")

        if isinstance(validation_issues, list):
            if validation_issues:
                parts.append(f"工序校验发现 {len(validation_issues)} 项需要关注的问题。")
            else:
                parts.append("工序校验未发现明显规则问题。")

        return "".join(parts)

    def _summarize_observation(self, output: dict[str, Any]) -> str:
        parts: list[str] = []
        parse_result = output.get("parse_result") if isinstance(output.get("parse_result"), dict) else {}
        process_plan = output.get("process_plan") if isinstance(output.get("process_plan"), dict) else {}
        validation_issues = output.get("validation_issues")
        if parse_result:
            part = parse_result.get("part") if isinstance(parse_result.get("part"), dict) else {}
            part_name = part.get("name") or part.get("part_name") or ""
            parts.append(f"图纸解析完成{f'，零件：{part_name}' if part_name else ''}")
            risks = parse_result.get("risk_flags") if isinstance(parse_result.get("risk_flags"), list) else []
            if risks:
                parts.append(f"风险 {len(risks)} 项")
        if process_plan:
            operations = process_plan.get("operations") if isinstance(process_plan.get("operations"), list) else []
            parts.append(f"工序方案 {len(operations)} 道")
        if isinstance(validation_issues, list):
            parts.append(f"校验问题 {len(validation_issues)} 项" if validation_issues else "校验通过")
        if output.get("pages"):
            pages = output.get("pages")
            if isinstance(pages, list):
                parts.append(f"页面渲染 {len(pages)} 页")
        if output.get("geometry") and isinstance(output.get("geometry"), dict):
            geometry = output.get("geometry")
            summary = geometry.get("summary")
            if summary:
                parts.append(str(summary))
        return "；".join(parts) or "工具已返回结果。"

    def _drawing_summary(self, parse_result: Any) -> dict[str, Any]:
        if not isinstance(parse_result, dict):
            return {}
        part = parse_result.get("part") if isinstance(parse_result.get("part"), dict) else {}
        features = parse_result.get("features") if isinstance(parse_result.get("features"), list) else []
        tolerances = parse_result.get("tolerances") if isinstance(parse_result.get("tolerances"), list) else []
        requirements = parse_result.get("technical_requirements") if isinstance(parse_result.get("technical_requirements"), list) else []
        inspections = parse_result.get("inspection_requirements") if isinstance(parse_result.get("inspection_requirements"), list) else []
        risks = parse_result.get("risk_flags") if isinstance(parse_result.get("risk_flags"), list) else []
        return {
            "part_name": part.get("part_name") or part.get("name") or "未识别",
            "drawing_no": part.get("drawing_no") or "",
            "material": part.get("material") or "",
            "heat_treatment": part.get("heat_treatment") or "",
            "feature_count": len(features),
            "tolerance_count": len(tolerances),
            "requirement_count": len(requirements),
            "inspection_count": len(inspections),
            "risk_count": len(risks),
            "key_features": [self._named_item(item) for item in features[:6] if isinstance(item, dict)],
            "key_requirements": [str(item.get("content") or item.get("source_text") or "") for item in requirements[:6] if isinstance(item, dict)],
        }

    def _operation_cards(self, process_plan: Any) -> list[dict[str, Any]]:
        if not isinstance(process_plan, dict):
            return []
        operations = process_plan.get("operations") if isinstance(process_plan.get("operations"), list) else []
        cards: list[dict[str, Any]] = []
        for operation in operations[:30]:
            if not isinstance(operation, dict):
                continue
            cards.append(
                {
                    "operation_no": operation.get("operation_no") or "",
                    "operation_name": operation.get("operation_name") or "",
                    "content": operation.get("content") or "",
                    "tools": self._string_list(operation.get("tools"))[:4],
                    "equipment": self._string_list(operation.get("equipment"))[:4],
                    "quality_gates": self._string_list(operation.get("quality_gates") or operation.get("control_points"))[:4],
                    "inspection_items": self._string_list(operation.get("inspection_items"))[:4],
                    "requires_manual_review": bool(operation.get("requires_manual_review")),
                }
            )
        return cards

    def _validation_issue_cards(self, validation_issues: Any) -> list[dict[str, Any]]:
        if not isinstance(validation_issues, list):
            return []
        issues: list[dict[str, Any]] = []
        for issue in validation_issues[:12]:
            if isinstance(issue, dict):
                issues.append(
                    {
                        "severity": issue.get("severity") or "warning",
                        "operation_no": issue.get("operation_no") or "",
                        "message": issue.get("message") or issue.get("code") or "需要人工复核",
                    }
                )
            elif issue:
                issues.append({"severity": "warning", "operation_no": "", "message": str(issue)})
        return issues

    def _next_step_suggestions(
        self,
        run: AgentRun,
        latest: dict[str, Any],
        final_result: dict[str, Any],
    ) -> list[str]:
        suggestions: list[str] = []
        if run.questions:
            suggestions.extend([f"补充确认：{item}" for item in run.questions[-3:]])
        if latest.get("process_plan"):
            suggestions.append("确认工序顺序和关键参数后，可继续让 Agent 生成工艺图或导出工序说明。")
        elif latest.get("parse_result"):
            suggestions.append("可以继续要求 Agent 基于图纸解析结果生成工序方案。")
        if final_result.get("questions") and isinstance(final_result.get("questions"), list):
            suggestions.extend([str(item) for item in final_result["questions"][:3] if item])
        if not suggestions:
            suggestions.append("可以继续追问具体工序、风险原因或要求导出结果。")
        return list(dict.fromkeys(suggestions))[:5]

    def _named_item(self, item: dict[str, Any]) -> str:
        return str(item.get("name") or item.get("description") or item.get("source_text") or "").strip()

    def _string_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value if item]
        if value:
            return [str(value)]
        return []

    def _latest_outputs(self, run: AgentRun) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for observation in run.observations:
            if not observation.ok:
                continue
            for key, value in (observation.output or {}).items():
                values[key] = value
        if run.final_result:
            latest_outputs = run.final_result.get("latest_outputs")
            if isinstance(latest_outputs, dict):
                values.update(latest_outputs)
        return values


response_module = ResponseModule()
