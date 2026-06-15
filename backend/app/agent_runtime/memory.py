from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agent_runtime.state import AgentRun
from app.agent_tools.contracts import AgentToolObservation


class AgentMemorySnapshot(BaseModel):
    short_term: dict[str, Any] = Field(default_factory=dict)
    long_term_refs: list[dict[str, Any]] = Field(default_factory=list)


class MemoryModule:
    def build_snapshot(
        self,
        *,
        run: AgentRun,
        perception: dict[str, Any],
        observations: list[AgentToolObservation] | None = None,
    ) -> AgentMemorySnapshot:
        recent_observations = [
            observation.model_dump(mode="json")
            for observation in (observations or run.observations)[-8:]
        ]
        short_term = {
            "goal": run.goal,
            "current_step": run.current_step,
            "plan": run.plan[-6:],
            "input_files": run.input_files,
            "perception": perception,
            "recent_observations": recent_observations,
            "risks": run.risks[-8:],
            "questions": run.questions[-8:],
        }
        long_term_refs = [
            {
                "source": "case_tools",
                "hint": "需要历史经验时优先调用 search_cases 或 load_case_summary。",
            },
            {
                "source": "knowledge_base",
                "hint": "业务长期记忆当前由案例库和 knowledge_base 目录承载。",
            },
        ]
        return AgentMemorySnapshot(short_term=short_term, long_term_refs=long_term_refs)


memory_module = MemoryModule()
