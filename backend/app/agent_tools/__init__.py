from __future__ import annotations

from app.agent_tools.registry import agent_tool_registry
from app.agent_tools.builtin import builtin_agent_tools


def init_agent_tools() -> None:
    if agent_tool_registry.list_specs():
        return
    agent_tool_registry.register_many(builtin_agent_tools())