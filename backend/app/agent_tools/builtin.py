from __future__ import annotations

from app.agent_tools.case_tools import case_agent_tools
from app.agent_tools.contracts import AgentToolDefinition
from app.agent_tools.drawing_tools import drawing_agent_tools
from app.agent_tools.process_tools import process_agent_tools


def builtin_agent_tools() -> list[AgentToolDefinition]:
    tools: list[AgentToolDefinition] = []
    tools.extend(drawing_agent_tools())
    tools.extend(process_agent_tools())
    tools.extend(case_agent_tools())
    return tools