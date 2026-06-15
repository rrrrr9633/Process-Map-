from __future__ import annotations

from app.agent_tools.contracts import AgentToolPermission
from app.agent_tools.registry import agent_tool_registry


def agent_tool_manifest(max_permission: AgentToolPermission = AgentToolPermission.WRITE) -> dict:
    specs = agent_tool_registry.list_specs(max_permission=max_permission)
    readonly_model_tools = [
        spec.name
        for spec in specs
        if spec.model_callable and spec.permission == AgentToolPermission.READ_ONLY
    ]
    generation_tools = [
        spec.name
        for spec in specs
        if spec.permission == AgentToolPermission.GENERATE
    ]
    confirmation_tools = [
        spec.name
        for spec in specs
        if spec.requires_human_confirmation
    ]
    return {
        "tool_count": len(specs),
        "default_model_tools": readonly_model_tools,
        "generation_tools": generation_tools,
        "human_confirmation_tools": confirmation_tools,
        "recommended_agent_policy": {
            "default_max_permission": AgentToolPermission.READ_ONLY.value,
            "allow_generate_after_plan": True,
            "require_human_confirmation_for_write": True,
            "never_trust_generated_annotations_without_review": True,
        },
        "recommended_open_source_integrations": [
            {
                "name": "LangGraph",
                "purpose": "把工具调用升级为可暂停、可恢复、可人工确认的有状态 agent workflow。",
            },
            {
                "name": "LlamaIndex",
                "purpose": "把案例库、工艺文档和历史标注接入 RAG 检索层。",
            },
            {
                "name": "Qdrant",
                "purpose": "为相似案例、相似标注和工艺片段提供向量检索。",
            },
            {
                "name": "PaddleOCR",
                "purpose": "增强中文工程图 OCR 和图片标注提取。",
            },
            {
                "name": "OpenTelemetry",
                "purpose": "记录 agent run、tool call、耗时、失败类型和人工确认链路。",
            },
        ],
    }
