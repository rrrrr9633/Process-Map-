from __future__ import annotations

from typing import Iterable

from app.agent_tools.contracts import (
    AgentToolCall,
    AgentToolDefinition,
    AgentToolObservation,
    AgentToolPermission,
    AgentToolSpec,
    run_tool_handler,
)


class AgentToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, AgentToolDefinition] = {}

    def register(self, definition: AgentToolDefinition) -> None:
        name = definition.spec.name
        if name in self._tools:
            raise ValueError(f"Agent tool already registered: {name}")
        self._tools[name] = definition

    def register_many(self, definitions: Iterable[AgentToolDefinition]) -> None:
        for definition in definitions:
            self.register(definition)

    def get(self, name: str) -> AgentToolDefinition:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ValueError(f"Unknown agent tool: {name}") from exc

    def list_specs(
        self,
        *,
        model_callable_only: bool = False,
        max_permission: AgentToolPermission | None = None,
    ) -> list[AgentToolSpec]:
        specs = [definition.spec for definition in self._tools.values()]
        if model_callable_only:
            specs = [spec for spec in specs if spec.model_callable]
        if max_permission:
            specs = [spec for spec in specs if _permission_rank(spec.permission) <= _permission_rank(max_permission)]
        return specs

    def call(self, call: AgentToolCall) -> AgentToolObservation:
        definition = self.get(call.tool_name)
        return run_tool_handler(definition.spec.name, definition.handler, call.arguments)


def _permission_rank(permission: AgentToolPermission) -> int:
    order = {
        AgentToolPermission.READ_ONLY: 1,
        AgentToolPermission.GENERATE: 2,
        AgentToolPermission.WRITE: 3,
    }
    return order[permission]


agent_tool_registry = AgentToolRegistry()