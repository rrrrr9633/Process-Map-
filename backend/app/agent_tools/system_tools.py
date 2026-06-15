from __future__ import annotations

from typing import Any

from app.agent_tools.contracts import (
    AgentToolCategory,
    AgentToolDefinition,
    AgentToolPermission,
    AgentToolSpec,
)
from app.services.case_service import case_service


def system_agent_tools() -> list[AgentToolDefinition]:
    return [
        AgentToolDefinition(
            spec=AgentToolSpec(
                name="get_case_storage_status",
                description="读取案例库 MySQL 与兼容 JSON 存储状态，用于诊断后端数据可用性。",
                category=AgentToolCategory.CASE,
                permission=AgentToolPermission.READ_ONLY,
                input_schema={},
                output_schema={"storage_status": "dict"},
                model_callable=True,
                cacheable=False,
                max_runtime_seconds=10,
            ),
            handler=get_case_storage_status_tool,
        )
    ]


def get_case_storage_status_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    return {"storage_status": case_service.storage_status()}
