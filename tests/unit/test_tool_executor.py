"""Unit tests for tools/executor.py."""

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.models import ToolConfig, ToolDependencyConfig, ToolMappingConfig
from tools.executor import (
    PlannedToolCall,
    ToolExecutionPlan,
    ToolExecutionResult,
    execute_tool_plan,
)
from tools.registry import LoadedTool


def _make_loaded_tool(tool_id: str, handler, depends_on=None):
    config = ToolConfig(
        id=tool_id,
        name=tool_id,
        description=f"Tool {tool_id}",
        handler=f"demo.tools.weather.{tool_id}",
        input_schema={"type": "object", "properties": {}, "required": []},
        output_schema={"type": "object", "properties": {}},
        depends_on=depends_on or [],
    )
    return LoadedTool(config=config, handler=handler)


def _make_mock_transformer():
    mock = AsyncMock()
    mock.complete = AsyncMock()
    return mock


@pytest.mark.asyncio
async def test_single_tool_executes_successfully():
    """A plan with one tool executes and returns success result."""
    async def my_tool():
        return {"answer": 42}

    loaded = {"tool_a": _make_loaded_tool("tool_a", my_tool)}
    plan = ToolExecutionPlan(
        tools=[PlannedToolCall("tool_a", {}, [])],
    )
    results, _ = await execute_tool_plan(plan, "test_agent", loaded, _make_mock_transformer())

    assert len(results) == 1
    assert results[0].status == "success"
    assert results[0].output == {"answer": 42}
    assert results[0].execution_mode == "sequential"


@pytest.mark.asyncio
async def test_two_independent_tools_run_in_parallel():
    """Two tools with no deps should run concurrently (timing check)."""
    delay = 0.3

    async def slow_tool_a(**kwargs):
        await asyncio.sleep(delay)
        return {"from": "a"}

    async def slow_tool_b(**kwargs):
        await asyncio.sleep(delay)
        return {"from": "b"}

    loaded = {
        "tool_a": _make_loaded_tool("tool_a", slow_tool_a),
        "tool_b": _make_loaded_tool("tool_b", slow_tool_b),
    }
    plan = ToolExecutionPlan(tools=[
        PlannedToolCall("tool_a", {}, []),
        PlannedToolCall("tool_b", {}, []),
    ])

    start = time.time()
    results, _ = await execute_tool_plan(plan, "test_agent", loaded, _make_mock_transformer())
    elapsed = time.time() - start

    # Both successful
    assert all(r.status == "success" for r in results)
    # Ran in parallel: elapsed should be ~delay, not ~2*delay
    assert elapsed < delay * 1.8, f"Expected parallel execution but took {elapsed:.2f}s"
    assert all(r.execution_mode == "parallel" for r in results)


@pytest.mark.asyncio
async def test_dependency_chain_b_gets_a_output():
    """Tool B depends on Tool A — B's input includes A's output field."""
    received_params = {}

    async def tool_a(**kwargs):
        return {"location": "Dhaka"}

    async def tool_b(location, **kwargs):
        received_params["location"] = location
        return {"forecast": "sunny"}

    dep_config = ToolDependencyConfig(
        tool_id="tool_a",
        mappings=[ToolMappingConfig(source_field="location", target_field="location")],
    )
    loaded = {
        "tool_a": _make_loaded_tool("tool_a", tool_a),
        "tool_b": _make_loaded_tool("tool_b", tool_b, depends_on=[dep_config]),
    }
    plan = ToolExecutionPlan(tools=[
        PlannedToolCall("tool_a", {}, []),
        PlannedToolCall("tool_b", {}, ["tool_a"]),
    ])

    results, _ = await execute_tool_plan(plan, "test_agent", loaded, _make_mock_transformer())

    assert all(r.status == "success" for r in results)
    assert received_params.get("location") == "Dhaka"


@pytest.mark.asyncio
async def test_failed_tool_does_not_block_independent_tools():
    """If tool A fails, independent tool B still runs."""
    async def failing_tool(**kwargs):
        raise RuntimeError("Intentional failure")

    async def healthy_tool(**kwargs):
        return {"ok": True}

    loaded = {
        "tool_a": _make_loaded_tool("tool_a", failing_tool),
        "tool_b": _make_loaded_tool("tool_b", healthy_tool),
    }
    plan = ToolExecutionPlan(tools=[
        PlannedToolCall("tool_a", {}, []),
        PlannedToolCall("tool_b", {}, []),
    ])

    results, _ = await execute_tool_plan(plan, "test_agent", loaded, _make_mock_transformer())

    by_id = {r.tool_id: r for r in results}
    assert by_id["tool_a"].status == "failed"
    assert by_id["tool_b"].status == "success"


@pytest.mark.asyncio
async def test_downstream_of_failed_tool_also_fails():
    """If tool A fails, tool B which depends on A also fails."""
    async def failing_tool(**kwargs):
        raise RuntimeError("A failed")

    async def dependent_tool(**kwargs):
        return {"result": "should not run"}

    dep_config = ToolDependencyConfig(
        tool_id="tool_a",
        mappings=[ToolMappingConfig(source_field="x", target_field="x")],
    )
    loaded = {
        "tool_a": _make_loaded_tool("tool_a", failing_tool),
        "tool_b": _make_loaded_tool("tool_b", dependent_tool, depends_on=[dep_config]),
    }
    plan = ToolExecutionPlan(tools=[
        PlannedToolCall("tool_a", {}, []),
        PlannedToolCall("tool_b", {}, ["tool_a"]),
    ])

    results, _ = await execute_tool_plan(plan, "test_agent", loaded, _make_mock_transformer())

    by_id = {r.tool_id: r for r in results}
    assert by_id["tool_a"].status == "failed"
    assert by_id["tool_b"].status == "failed"
    assert "upstream dependency failed" in by_id["tool_b"].error


@pytest.mark.asyncio
async def test_empty_plan_returns_empty():
    """Empty tool plan returns empty results immediately."""
    plan = ToolExecutionPlan(tools=[])
    results, records = await execute_tool_plan(plan, "test_agent", {}, _make_mock_transformer())
    assert results == []
    assert records == []
