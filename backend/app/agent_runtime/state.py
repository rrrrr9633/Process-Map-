from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.agent_tools.contracts import AgentToolCall, AgentToolObservation


class AgentRunStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentRunEventType(str, Enum):
    RUN_CREATED = "run_created"
    PLAN_CREATED = "plan_created"
    TOOL_REQUESTED = "tool_requested"
    TOOL_COMPLETED = "tool_completed"
    OBSERVATION_RECORDED = "observation_recorded"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"


class AgentRunArtifact(BaseModel):
    artifact_id: str = Field(default_factory=lambda: uuid4().hex)
    kind: str
    title: str
    content: dict[str, Any] | list[Any] | str
    source_tool: str = ""
    confidence: float | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentRunEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    event_type: AgentRunEventType
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentRun(BaseModel):
    run_id: str = Field(default_factory=lambda: uuid4().hex)
    goal: str
    status: AgentRunStatus = AgentRunStatus.PENDING
    current_step: str = ""
    input_files: list[str] = Field(default_factory=list)
    plan: list[dict[str, Any]] = Field(default_factory=list)
    observations: list[AgentToolObservation] = Field(default_factory=list)
    tool_calls: list[AgentToolCall] = Field(default_factory=list)
    artifacts: list[AgentRunArtifact] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    final_result: dict[str, Any] | None = None
    events: list[AgentRunEvent] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def record_event(self, event_type: AgentRunEventType, message: str, payload: dict[str, Any] | None = None) -> None:
        self.events.append(AgentRunEvent(event_type=event_type, message=message, payload=payload or {}))
        self.updated_at = datetime.utcnow()

    def record_tool_observation(self, call: AgentToolCall, observation: AgentToolObservation) -> None:
        self.tool_calls.append(call)
        self.observations.append(observation)
        self.record_event(
            AgentRunEventType.TOOL_COMPLETED,
            f"工具 {call.tool_name} 执行{'成功' if observation.ok else '失败'}",
            {"call": call.model_dump(mode="json"), "observation": observation.model_dump(mode="json")},
        )
        if observation.requires_human_review:
            self.status = AgentRunStatus.WAITING_HUMAN
            self.record_event(AgentRunEventType.HUMAN_REVIEW_REQUIRED, f"工具 {call.tool_name} 结果需要人工复核")