"""Sub-agent node — handles tool selection, execution, and intra-aggregation."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from langchain_core.runnables import RunnableConfig

from core.context import AppContext
from core.state import AgentResult, OrchestrationState
from llm.base import LLMCallRecord
from tools.executor import PlannedToolCall, ToolExecutionPlan, execute_tool_plan

logger = logging.getLogger(__name__)

_TOOL_PLAN_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "tools": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tool_id": {"type": "string"},
                    "initial_params": {"type": "object"},
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["tool_id", "initial_params", "depends_on"],
            },
        },
        "direct_response": {"type": "string"},
    },
    "required": ["tools"],
}

_MAX_TOOL_OUTPUT_CHARS = 2000


class SubAgentError(Exception):
    """Raised when a sub-agent encounters an unrecoverable error."""


async def sub_agent_node(
    state: OrchestrationState,
    config: RunnableConfig,
) -> Dict[str, Any]:
    """LangGraph node: run one sub-agent end-to-end.

    Reads current_agent_task from state (set by Send fan-out), performs
    tool selection, tool execution, and intra-aggregation. Writes to
    agent_results[agent_id]. All exceptions are caught and result in a
    failed AgentResult.

    Args:
        state: Current orchestration state for this branch.
        config: LangGraph config with app_context and status_queue.

    Returns:
        Partial state update with agent_results, execution_trace, llm_call_log.
    """
    app_context: AppContext = config["configurable"]["app_context"]
    status_queue = config["configurable"].get("status_queue")

    agent_task = state["current_agent_task"]
    agent_id = agent_task["agent_id"]
    sub_query = agent_task["sub_query"]
    new_llm_records: List[Dict[str, Any]] = []

    if status_queue is not None:
        agent_name = app_context.agent_configs.get(agent_id, {})
        name = agent_name.name if hasattr(agent_name, "name") else agent_id
        status_queue.put({
            "type": "agent_started",
            "agent_id": agent_id,
            "agent_name": name,
        })

    try:
        # ── Step 1: Tool Selection ──────────────────────────────────────────
        plan, tool_sel_record = await _select_tools(
            agent_id=agent_id,
            sub_query=sub_query,
            app_context=app_context,
        )
        if tool_sel_record:
            new_llm_records.append(tool_sel_record.to_dict())

        # ── Step 2: Handle Direct Response ─────────────────────────────────
        if plan.direct_response is not None:
            agent_result: AgentResult = {
                "agent_id": agent_id,
                "status": "success",
                "response": plan.direct_response,
                "tool_executions": [],
                "error": None,
            }
            if status_queue is not None:
                status_queue.put({"type": "agent_done", "agent_id": agent_id, "status": "success"})
            return {
                "agent_results": {agent_id: agent_result},
                "llm_call_log": new_llm_records,
            }

        # ── Step 3: Execute Tools ───────────────────────────────────────────
        loaded_tools = app_context.tool_registry.get_agent_tools(agent_id)
        tool_results, exec_llm_records = await execute_tool_plan(
            plan=plan,
            agent_id=agent_id,
            loaded_tools=loaded_tools,
            transformer_llm=app_context.transformer_llm,
            status_queue=status_queue,
        )
        new_llm_records.extend([r.to_dict() for r in exec_llm_records])

        # ── Step 4: Intra-Agent Aggregation ────────────────────────────────
        agent_response, agg_record = await _aggregate_tool_results(
            sub_query=sub_query,
            tool_results=tool_results,
            aggregator_llm=app_context.aggregator_llm,
        )
        if agg_record:
            new_llm_records.append(agg_record.to_dict())

        trace_dicts = [r.to_dict() for r in tool_results]
        agent_result = {
            "agent_id": agent_id,
            "status": "success",
            "response": agent_response,
            "tool_executions": trace_dicts,
            "error": None,
        }

        if status_queue is not None:
            status_queue.put({"type": "agent_done", "agent_id": agent_id, "status": "success"})

        return {
            "agent_results": {agent_id: agent_result},
            "execution_trace": trace_dicts,
            "llm_call_log": new_llm_records,
        }

    except Exception as e:
        logger.exception("Sub-agent '%s' failed: %s", agent_id, e)
        failed_result: AgentResult = {
            "agent_id": agent_id,
            "status": "failed",
            "response": "",
            "tool_executions": [],
            "error": str(e),
        }
        if status_queue is not None:
            status_queue.put({"type": "agent_done", "agent_id": agent_id, "status": "failed"})
        return {
            "agent_results": {agent_id: failed_result},
            "llm_call_log": new_llm_records,
        }


async def _select_tools(
    agent_id: str,
    sub_query: str,
    app_context: AppContext,
) -> tuple[ToolExecutionPlan, Optional[LLMCallRecord]]:
    """Call the tool-selector LLM to get a ToolExecutionPlan."""
    loaded_tools_dict = app_context.tool_registry.get_agent_tools(agent_id)

    # Include the exact tool_id in the description so the LLM returns the
    # correct id (not the display name) in its JSON response.
    tools_desc = "\n".join(
        f"- tool_id: \"{tool_id}\"\n"
        f"  description: {loaded.config.description}\n"
        f"  input_schema: {json.dumps(loaded.config.input_schema)}"
        for tool_id, loaded in loaded_tools_dict.items()
    )
    system_prompt = (
        "You are a tool selection assistant. Given a user sub-query and available tools, "
        "decide which tools to call and in what order.\n\n"
        f"Available tools:\n{tools_desc}\n\n"
        "Instructions:\n"
        "- Use the EXACT tool_id string shown above — do not paraphrase or rename it.\n"
        "- Select only the tools needed to answer the query.\n"
        "- For each tool, provide 'initial_params' (params determinable from the query alone).\n"
        "- For params that come from another tool's output, leave them empty — "
        "the dependency resolver will fill them.\n"
        "- If tool B needs tool A's output, set depends_on: ['tool_a_id'].\n"
        "- If no tools are needed, set tools to [] and provide a direct_response.\n"
        "- Return valid JSON only."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": sub_query},
    ]

    llm_response = await app_context.tool_selector_llm.complete(
        messages=messages,
        structured_output_schema=_TOOL_PLAN_SCHEMA,
    )

    plan_data = json.loads(llm_response.content)

    call_record = LLMCallRecord(
        role="tool_selector",
        provider=app_context.app_config.llm_roles.tool_selector.provider,
        model=llm_response.model,
        input_tokens=llm_response.input_tokens,
        output_tokens=llm_response.output_tokens,
        timestamp=time.time(),
    )

    # Validate and filter planned tools
    valid_tool_ids = set(app_context.tool_registry.get_agent_tools(agent_id).keys())
    planned_calls: List[PlannedToolCall] = []
    for t in plan_data.get("tools", []):
        tid = t.get("tool_id", "")
        if tid not in valid_tool_ids:
            logger.warning("Tool selector returned unknown tool '%s' for agent '%s' — skipping", tid, agent_id)
            continue
        planned_calls.append(PlannedToolCall(
            tool_id=tid,
            initial_params=t.get("initial_params", {}),
            depends_on=t.get("depends_on", []),
        ))

    direct_response = plan_data.get("direct_response") or None
    if not planned_calls and not direct_response:
        direct_response = "I could not determine how to answer this with the available tools."

    # Detect cycles in planned dependency graph
    dep_graph: Dict[str, List[str]] = {p.tool_id: p.depends_on for p in planned_calls}
    _check_cycles(dep_graph, agent_id)

    plan = ToolExecutionPlan(tools=planned_calls, direct_response=direct_response)
    logger.debug(
        "Tool plan for agent '%s': %d tools, direct_response=%s",
        agent_id,
        len(planned_calls),
        direct_response is not None,
    )
    return plan, call_record


def _check_cycles(dep_graph: Dict[str, List[str]], agent_id: str) -> None:
    """Detect cycles in the tool dependency graph. Raises SubAgentError on cycle."""
    visited: set = set()
    rec_stack: set = set()

    def dfs(node: str) -> None:
        visited.add(node)
        rec_stack.add(node)
        for neighbor in dep_graph.get(node, []):
            if neighbor not in visited:
                dfs(neighbor)
            elif neighbor in rec_stack:
                raise SubAgentError(
                    f"Circular tool dependency detected in agent '{agent_id}' involving '{neighbor}'"
                )
        rec_stack.discard(node)

    for tid in dep_graph:
        if tid not in visited:
            dfs(tid)


async def _aggregate_tool_results(
    sub_query: str,
    tool_results: list,
    aggregator_llm: Any,
) -> tuple[str, Optional[LLMCallRecord]]:
    """Aggregate tool execution results into a natural language response."""
    if not tool_results:
        return "I was unable to retrieve the information needed to answer this.", None

    all_failed = all(r.status == "failed" for r in tool_results)
    if all_failed:
        return "I was unable to retrieve the information needed to answer this.", None

    result_parts: List[str] = []
    for r in tool_results:
        if r.status == "success" and r.output:
            summary = json.dumps(r.output)[:_MAX_TOOL_OUTPUT_CHARS]
            result_parts.append(f"[{r.tool_id}]: {summary}")
        else:
            result_parts.append(f"[{r.tool_id}]: UNAVAILABLE ({r.error or 'unknown error'})")

    results_text = "\n".join(result_parts)
    messages = [
        {
            "role": "system",
            "content": (
                "You are an assistant summarizing tool results for a user query. "
                "Synthesize the results into a single, coherent, conversational response. "
                "Do not mention tool names or technical details unless directly relevant."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Query: {sub_query}\n\n"
                f"Tool Results:\n{results_text}\n\n"
                "Provide a helpful response based on the above results."
            ),
        },
    ]

    llm_response = await aggregator_llm.complete(messages=messages)
    record = LLMCallRecord(
        role="aggregator",
        provider="configured",
        model=llm_response.model,
        input_tokens=llm_response.input_tokens,
        output_tokens=llm_response.output_tokens,
        timestamp=time.time(),
    )
    return llm_response.content, record
