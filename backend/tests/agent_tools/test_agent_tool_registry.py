from __future__ import annotations

from pathlib import Path

from app.agent_runtime.executor import ControlledAgentExecutor
from app.agent_runtime.state import AgentRunStatus
from app.agent_tools import init_agent_tools
from app.agent_tools.contracts import AgentToolPermission
from app.agent_tools.registry import agent_tool_registry


def test_builtin_agent_tools_register_once() -> None:
    init_agent_tools()
    init_agent_tools()

    specs = agent_tool_registry.list_specs()
    names = {spec.name for spec in specs}

    assert "parse_drawing" in names
    assert "render_drawing_pages" in names
    assert "analyze_3d_geometry" in names
    assert "validate_process_plan" in names
    assert "search_cases" in names


def test_model_callable_readonly_tools_are_filterable() -> None:
    init_agent_tools()

    specs = agent_tool_registry.list_specs(
        model_callable_only=True,
        max_permission=AgentToolPermission.READ_ONLY,
    )
    names = {spec.name for spec in specs}

    assert "parse_drawing" in names
    assert "validate_process_plan" in names
    assert "search_cases" in names
    assert "generate_rule_process_plan" not in names


def test_controlled_executor_blocks_generate_tool_by_default() -> None:
    init_agent_tools()
    executor = ControlledAgentExecutor(agent_tool_registry)
    run = executor.create_run(goal="测试只读工具权限")

    run = executor.run_tool(run, "generate_rule_process_plan", {"parse_result": {}})

    assert run.status == AgentRunStatus.FAILED
    assert run.events[-1].event_type.value == "run_failed"


def test_controlled_executor_waits_for_human_confirmation_on_write_tool() -> None:
    init_agent_tools()
    executor = ControlledAgentExecutor(agent_tool_registry)
    run = executor.create_run(goal="测试写工具人工确认")

    run = executor.run_tool(
        run,
        "save_case",
        {"case": {}},
        max_permission=AgentToolPermission.WRITE,
    )

    assert run.status == AgentRunStatus.WAITING_HUMAN
    assert not run.tool_calls
    assert run.events[-1].event_type.value == "human_review_required"


def test_parse_drawing_tool_records_observation(tmp_path: Path) -> None:
    init_agent_tools()
    source = tmp_path / "drawing.txt"
    source.write_text("曲轴 主轴颈 粗糙度 清洁度", encoding="utf-8")
    executor = ControlledAgentExecutor(agent_tool_registry)
    run = executor.create_run(goal="测试解析工具", input_files=[str(source)])

    run = executor.run_tool(run, "parse_drawing", {"file_path": str(source)})

    assert run.tool_calls[-1].tool_name == "parse_drawing"
    assert run.observations[-1].ok
    assert "parse_result" in run.observations[-1].output
