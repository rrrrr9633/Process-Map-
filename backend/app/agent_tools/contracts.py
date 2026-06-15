from __future__ import annotations

from enum import Enum
from time import perf_counter
from typing import Any, Callable

from pydantic import BaseModel, Field


class AgentToolCategory(str, Enum):
    DRAWING = "drawing"
    PROCESS = "process"
    CASE = "case"
    EXPORT = "export"


class AgentToolPermission(str, Enum):
    READ_ONLY = "read_only"
    GENERATE = "generate"
    WRITE = "write"


class AgentToolFailureType(str, Enum):
    INVALID_INPUT = "invalid_input"
    UNSUPPORTED_FORMAT = "unsupported_format"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    SERVICE_ERROR = "service_error"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class AgentToolSpec(BaseModel):
    name: str
    description: str
    category: AgentToolCategory
    permission: AgentToolPermission = AgentToolPermission.READ_ONLY
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    model_callable: bool = False
    cacheable: bool = False
    requires_human_confirmation: bool = False
    max_runtime_seconds: float = 30


class AgentToolCall(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class AgentToolObservation(BaseModel):
    tool_name: str
    ok: bool
    output: dict[str, Any] = Field(default_factory=dict)
    error_type: AgentToolFailureType | None = None
    error_message: str = ""
    elapsed_ms: int = 0
    requires_human_review: bool = False


AgentToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


class AgentToolDefinition(BaseModel):
    spec: AgentToolSpec
    handler: AgentToolHandler = Field(exclude=True)

    class Config:
        arbitrary_types_allowed = True


def run_tool_handler(tool_name: str, handler: AgentToolHandler, arguments: dict[str, Any]) -> AgentToolObservation:
    started_at = perf_counter()
    try:
        output = handler(arguments)
        requires_review = bool(output.pop("requires_human_review", False)) if isinstance(output, dict) else False
        return AgentToolObservation(
            tool_name=tool_name,
            ok=True,
            output=output if isinstance(output, dict) else {"value": output},
            elapsed_ms=int((perf_counter() - started_at) * 1000),
            requires_human_review=requires_review,
        )
    except ValueError as exc:
        return _failure(tool_name, started_at, AgentToolFailureType.INVALID_INPUT, exc)
    except FileNotFoundError as exc:
        return _failure(tool_name, started_at, AgentToolFailureType.INVALID_INPUT, exc)
    except NotImplementedError as exc:
        return _failure(tool_name, started_at, AgentToolFailureType.UNSUPPORTED_FORMAT, exc)
    except TimeoutError as exc:
        return _failure(tool_name, started_at, AgentToolFailureType.TIMEOUT, exc)
    except Exception as exc:
        return _failure(tool_name, started_at, AgentToolFailureType.UNKNOWN, exc)


def _failure(
    tool_name: str,
    started_at: float,
    error_type: AgentToolFailureType,
    exc: Exception,
) -> AgentToolObservation:
    return AgentToolObservation(
        tool_name=tool_name,
        ok=False,
        error_type=error_type,
        error_message=f"{type(exc).__name__}: {exc}",
        elapsed_ms=int((perf_counter() - started_at) * 1000),
        requires_human_review=True,
    )