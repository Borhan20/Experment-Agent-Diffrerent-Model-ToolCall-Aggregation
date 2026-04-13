"""Tool execution engine — runs tools in dependency-ordered parallel/sequential batches."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from config.models import ToolDependencyConfig
from core import dependency_resolver
from llm.base import LLMAdapter, LLMCallRecord
from tools.registry import LoadedTool

logger = logging.getLogger(__name__)

TOOL_TIMEOUT_SECONDS = 30


@dataclass
class PlannedToolCall:
    """A tool call as planned by the tool-selector LLM."""
    tool_id: str
    initial_params: Dict[str, Any]
    depends_on: List[str]  # tool_ids this call waits for


@dataclass
class ToolExecutionPlan:
    """Output of the tool-selector LLM for a sub-agent."""
    tools: List[PlannedToolCall]
    direct_response: Optional[str] = None  # set when no tools needed


@dataclass
class ToolExecutionResult:
    """Result of executing one tool."""
    tool_id: str
    agent_id: str
    status: str                    # "success" | "failed"
    output: Optional[Dict[str, Any]]
    error: Optional[str]
    execution_mode: str            # "parallel" | "sequential"
    start_time: float
    end_time: float
    used_transformer_llm: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "agent_id": self.agent_id,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "execution_mode": self.execution_mode,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "used_transformer_llm": self.used_transformer_llm,
        }


async def execute_tool_plan(
    plan: ToolExecutionPlan,
    agent_id: str,
    loaded_tools: Dict[str, LoadedTool],
    transformer_llm: LLMAdapter,
    status_queue: Optional[Any] = None,
) -> tuple[List[ToolExecutionResult], List[LLMCallRecord]]:
    """Execute all tools in the plan respecting dependency order.

    Independent tools run in parallel via asyncio.gather.
    Dependent tools wait for their predecessors, with parameter resolution
    handled programmatically or via the cheap transformer LLM.

    Args:
        plan: The execution plan from the tool-selector LLM.
        agent_id: The owning agent (for logging and event emission).
        loaded_tools: Dict of tool_id → LoadedTool for this agent.
        transformer_llm: Cheap LLM for parameter transformation.
        status_queue: Optional queue for UI status events.

    Returns:
        Tuple of (results list, llm_call_records list).
    """
    if not plan.tools:
        return [], []

    # Build: tool_id → PlannedToolCall
    plan_map: Dict[str, PlannedToolCall] = {t.tool_id: t for t in plan.tools}

    completed: Dict[str, Dict[str, Any]] = {}   # tool_id → output dict
    failed: Set[str] = set()
    results: List[ToolExecutionResult] = []
    llm_records: List[LLMCallRecord] = []
    pending: Set[str] = set(plan_map.keys())

    while pending:
        # Find tools whose dependencies are all satisfied
        ready: Set[str] = {
            t for t in pending
            if all(dep in completed for dep in plan_map[t].depends_on)
            and not any(dep in failed for dep in plan_map[t].depends_on)
        }

        # Tools whose dependencies failed — mark them as failed immediately
        doomed: Set[str] = {
            t for t in pending
            if any(dep in failed for dep in plan_map[t].depends_on)
            and t not in ready
        }
        for tool_id in doomed:
            end_t = time.time()
            results.append(ToolExecutionResult(
                tool_id=tool_id,
                agent_id=agent_id,
                status="failed",
                output=None,
                error="upstream dependency failed",
                execution_mode="sequential",
                start_time=end_t,
                end_time=end_t,
                used_transformer_llm=False,
            ))
            failed.add(tool_id)
            pending.discard(tool_id)

        if not ready:
            if pending:
                # Remaining tools are stuck (cycle or all upstream failed)
                for tool_id in list(pending):
                    end_t = time.time()
                    results.append(ToolExecutionResult(
                        tool_id=tool_id,
                        agent_id=agent_id,
                        status="failed",
                        output=None,
                        error="upstream dependency failed or deadlock",
                        execution_mode="sequential",
                        start_time=end_t,
                        end_time=end_t,
                        used_transformer_llm=False,
                    ))
                    failed.add(tool_id)
                pending.clear()
            break

        execution_mode = "parallel" if len(ready) > 1 else "sequential"

        # Emit tool_started events
        for tool_id in ready:
            if status_queue is not None:
                loaded = loaded_tools.get(tool_id)
                tool_name = loaded.config.name if loaded else tool_id
                status_queue.put({
                    "type": "tool_started",
                    "agent_id": agent_id,
                    "tool_id": tool_id,
                    "tool_name": tool_name,
                    "mode": execution_mode,
                })

        # Execute ready tools concurrently
        tasks = [
            _execute_single_tool(
                tool_id=tool_id,
                agent_id=agent_id,
                planned=plan_map[tool_id],
                completed=completed,
                loaded_tools=loaded_tools,
                transformer_llm=transformer_llm,
                execution_mode=execution_mode,
            )
            for tool_id in ready
        ]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        for tool_id, result in zip(ready, batch_results):
            if isinstance(result, Exception):
                end_t = time.time()
                err_msg = str(result)
                results.append(ToolExecutionResult(
                    tool_id=tool_id,
                    agent_id=agent_id,
                    status="failed",
                    output=None,
                    error=err_msg,
                    execution_mode=execution_mode,
                    start_time=end_t,
                    end_time=end_t,
                    used_transformer_llm=False,
                ))
                failed.add(tool_id)
            else:
                exec_result, new_llm_records = result
                results.append(exec_result)
                llm_records.extend(new_llm_records)
                if exec_result.status == "success" and exec_result.output is not None:
                    completed[tool_id] = exec_result.output
                else:
                    failed.add(tool_id)

            # Emit tool_done event
            if status_queue is not None:
                r = results[-1]
                duration_ms = int((r.end_time - r.start_time) * 1000)
                status_queue.put({
                    "type": "tool_done",
                    "agent_id": agent_id,
                    "tool_id": tool_id,
                    "status": r.status,
                    "duration_ms": duration_ms,
                })

        pending -= ready

    return results, llm_records


async def _execute_single_tool(
    tool_id: str,
    agent_id: str,
    planned: PlannedToolCall,
    completed: Dict[str, Dict[str, Any]],
    loaded_tools: Dict[str, LoadedTool],
    transformer_llm: LLMAdapter,
    execution_mode: str,
) -> tuple[ToolExecutionResult, List[LLMCallRecord]]:
    """Execute a single tool with dependency parameter resolution."""
    start_t = time.time()
    llm_records: List[LLMCallRecord] = []
    used_llm = False

    loaded = loaded_tools.get(tool_id)
    if loaded is None:
        raise RuntimeError(f"Tool '{tool_id}' not found in registry")

    # Start with params planned by tool selector
    params: Dict[str, Any] = dict(planned.initial_params)

    # Resolve dependency parameters
    for dep_config in loaded.config.depends_on:
        if dep_config.tool_id not in completed:
            raise RuntimeError(
                f"Dependency '{dep_config.tool_id}' output not available for tool '{tool_id}'"
            )
        upstream_output = completed[dep_config.tool_id]
        try:
            resolved, dep_used_llm, llm_record = await dependency_resolver.resolve(
                upstream_output=upstream_output,
                dependency_config=dep_config,
                target_input_schema=loaded.config.input_schema,
                transformer_llm=transformer_llm,
            )
        except RuntimeError as e:
            raise RuntimeError(f"Dependency resolution failed for '{tool_id}': {e}") from e

        params.update(resolved)
        if dep_used_llm:
            used_llm = True
        if llm_record is not None:
            llm_records.append(llm_record)

    # Execute the tool handler with timeout
    try:
        handler = loaded.handler
        if inspect.iscoroutinefunction(handler):
            output = await asyncio.wait_for(handler(**params), timeout=TOOL_TIMEOUT_SECONDS)
        else:
            output = await asyncio.wait_for(
                asyncio.to_thread(handler, **params), timeout=TOOL_TIMEOUT_SECONDS
            )
    except asyncio.TimeoutError:
        end_t = time.time()
        return ToolExecutionResult(
            tool_id=tool_id,
            agent_id=agent_id,
            status="failed",
            output=None,
            error="tool timeout (>30s)",
            execution_mode=execution_mode,
            start_time=start_t,
            end_time=end_t,
            used_transformer_llm=used_llm,
        ), llm_records

    end_t = time.time()
    return ToolExecutionResult(
        tool_id=tool_id,
        agent_id=agent_id,
        status="success",
        output=output if isinstance(output, dict) else {"result": output},
        error=None,
        execution_mode=execution_mode,
        start_time=start_t,
        end_time=end_t,
        used_transformer_llm=used_llm,
    ), llm_records
