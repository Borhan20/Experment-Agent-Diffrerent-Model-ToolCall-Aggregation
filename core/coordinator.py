"""Coordinator node — routes user query to appropriate sub-agents."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from langchain_core.runnables import RunnableConfig

from core.context import AppContext
from core.state import AgentResult, AgentTask, OrchestrationState, RoutingPlan
from llm.base import LLMCallRecord

logger = logging.getLogger(__name__)


# JSON schema for the routing plan (used as structured_output_schema)
_ROUTING_PLAN_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "sub_query": {"type": "string"},
                },
                "required": ["agent_id", "sub_query"],
            },
        },
        "execution_mode": {
            "type": "string",
            "enum": ["parallel", "sequential"],
        },
        "routing_rationale": {"type": "string"},
    },
    "required": ["tasks", "execution_mode", "routing_rationale"],
}

_MAX_HISTORY_TURNS = 10   # 5 user + 5 assistant


class CoordinatorError(Exception):
    """Raised when the coordinator cannot produce a valid routing plan."""


async def coordinator_node(
    state: OrchestrationState,
    config: RunnableConfig,
) -> Dict[str, Any]:
    """LangGraph node: analyze query and produce a routing plan.

    Args:
        state: Current orchestration state.
        config: LangGraph config containing app_context and status_queue.

    Returns:
        Partial state update with routing_plan and llm_call_log entry.
    """
    app_context: AppContext = config["configurable"]["app_context"]
    status_queue = config["configurable"].get("status_queue")

    query = state["current_query"]
    if not query or not query.strip():
        raise ValueError("Empty query passed to coordinator")

    # Truncate conversation history to last N turns
    history = state.get("conversation_history", [])
    if len(history) > _MAX_HISTORY_TURNS * 2:
        history = history[-(_MAX_HISTORY_TURNS * 2):]

    # Build system prompt listing available agents
    agents_desc = "\n".join(
        f"- {agent.id}: {agent.description.strip()}"
        for agent in app_context.app_config.agents
    )
    system_prompt = (
        "You are a routing coordinator for a multi-agent AI system. "
        "Given the user's query, select which specialized agents should handle it.\n\n"
        f"Available agents:\n{agents_desc}\n\n"
        "Rules:\n"
        "- Select ONLY agents relevant to the query.\n"
        "- If the query spans multiple independent domains, set execution_mode to 'parallel'.\n"
        "- Assign each agent only the portion of the query relevant to it.\n"
        "- The sub_query must be self-contained — the agent won't see the full query.\n"
        "- If no agent is relevant, return an empty tasks list.\n"
        "- Return valid JSON only."
    )

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        if msg["role"] in ("user", "assistant"):
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": query})

    # Call router LLM (high-capability) — retry once on failure
    plan_data: Optional[Dict[str, Any]] = None
    llm_response = None
    for attempt in range(2):
        try:
            llm_response = await app_context.router_llm.complete(
                messages=messages,
                structured_output_schema=_ROUTING_PLAN_SCHEMA,
            )
            plan_data = json.loads(llm_response.content)
            break
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Coordinator LLM attempt %d failed: %s", attempt + 1, e)
            if attempt == 1:
                raw = llm_response.content if llm_response else "(no response)"
                logger.error("Raw coordinator output: %s", raw)
                raise CoordinatorError(
                    f"Router LLM failed to produce valid routing plan after 2 attempts: {e}"
                ) from e

    # Log LLM call
    call_record = LLMCallRecord(
        role="router",
        provider=app_context.app_config.llm_roles.router.provider,
        model=llm_response.model,
        input_tokens=llm_response.input_tokens,
        output_tokens=llm_response.output_tokens,
        timestamp=time.time(),
    )
    logger.debug("Routing rationale: %s", plan_data.get("routing_rationale", ""))

    # Validate agent IDs
    valid_agent_ids = {a.id for a in app_context.app_config.agents}
    valid_tasks: List[AgentTask] = []
    for task in plan_data.get("tasks", []):
        aid = task.get("agent_id", "")
        if aid in valid_agent_ids:
            valid_tasks.append(AgentTask(agent_id=aid, sub_query=task.get("sub_query", query)))
        else:
            logger.warning("Coordinator returned unknown agent_id '%s' — skipping", aid)

    if not valid_tasks:
        # No valid agents — produce a direct fallback response
        routing_plan = RoutingPlan(
            tasks=[],
            execution_mode="parallel",
            routing_rationale=plan_data.get("routing_rationale", "No matching agent"),
        )
        fallback_result: AgentResult = {
            "agent_id": "__fallback__",
            "status": "success",
            "response": "I don't have a specialized agent for this type of query.",
            "tool_executions": [],
            "error": None,
        }
        return {
            "routing_plan": routing_plan,
            "agent_results": {"__fallback__": fallback_result},
            "final_response": fallback_result["response"],
            "llm_call_log": [call_record.to_dict()],
        }

    routing_plan = RoutingPlan(
        tasks=valid_tasks,
        execution_mode=plan_data.get("execution_mode", "parallel"),
        routing_rationale=plan_data.get("routing_rationale", ""),
    )

    if status_queue is not None:
        status_queue.put({"type": "routing_done", "agent_count": len(valid_tasks)})

    return {
        "routing_plan": routing_plan,
        "llm_call_log": [call_record.to_dict()],
    }
