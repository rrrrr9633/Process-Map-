from __future__ import annotations

from app.agent_tools.annotation_tools import annotation_agent_tools
from app.agent_tools.case_tools import case_agent_tools
from app.agent_tools.case_write_tools import case_write_agent_tools
from app.agent_tools.contracts import AgentToolDefinition
from app.agent_tools.drawing_tools import drawing_agent_tools
from app.agent_tools.export_tools import export_agent_tools
from app.agent_tools.final_guidance_tools import final_guidance_agent_tools
from app.agent_tools.process_tools import process_agent_tools
from app.agent_tools.process_drawing_tools import process_drawing_agent_tools
from app.agent_tools.system_tools import system_agent_tools


def builtin_agent_tools() -> list[AgentToolDefinition]:
    tools: list[AgentToolDefinition] = []
    tools.extend(drawing_agent_tools())
    tools.extend(annotation_agent_tools())
    tools.extend(process_agent_tools())
    tools.extend(final_guidance_agent_tools())
    tools.extend(process_drawing_agent_tools())
    tools.extend(case_agent_tools())
    tools.extend(case_write_agent_tools())
    tools.extend(export_agent_tools())
    tools.extend(system_agent_tools())
    return tools
