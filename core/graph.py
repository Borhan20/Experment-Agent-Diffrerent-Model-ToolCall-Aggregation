"""Main LangGraph graph definition — coordinator → fan-out → cross-aggregator."""

from __future__ import annotations

import logging
from typing import List, Union

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from core.aggregator import cross_aggregator_node
from core.coordinator import coordinator_node
from core.state import OrchestrationState
from core.sub_agent import sub_agent_node

logger = logging.getLogger(__name__)


def _route_to_agents(state: OrchestrationState) -> Union[List[Send], str]:
    """Edge function: fan out to sub-agents based on routing plan.

    Returns a list of Send objects — one per AgentTask in the plan.
    LangGraph executes all Sends concurrently (parallel fan-out).

    If the coordinator already set final_response (no-agent fallback case),
    route directly to END.
    """
    # If coordinator handled the response directly (no valid agents)
    if state.get("final_response"):
        return "cross_aggregator"

    routing_plan = state.get("routing_plan")
    if not routing_plan or not routing_plan.get("tasks"):
        logger.warning("Empty routing plan — routing to cross_aggregator for fallback")
        return "cross_aggregator"

    sends = [
        Send("run_sub_agent", {**state, "current_agent_task": task})
        for task in routing_plan["tasks"]
    ]
    logger.debug("Fan-out: dispatching %d sub-agent(s)", len(sends))
    return sends


def build_graph() -> StateGraph:
    """Build and compile the main orchestration graph.

    Graph structure:
        START → coordinator → [Send×N] → run_sub_agent → cross_aggregator → END

    Returns:
        Compiled LangGraph application ready for ainvoke().
    """
    graph = StateGraph(OrchestrationState)

    graph.add_node("coordinator", coordinator_node)
    graph.add_node("run_sub_agent", sub_agent_node)
    graph.add_node("cross_aggregator", cross_aggregator_node)

    graph.add_edge(START, "coordinator")

    graph.add_conditional_edges(
        "coordinator",
        _route_to_agents,
        ["run_sub_agent", "cross_aggregator"],
    )

    graph.add_edge("run_sub_agent", "cross_aggregator")
    graph.add_edge("cross_aggregator", END)

    return graph.compile()


# Module-level compiled graph — built once at import time.
# This is re-used for all requests.
compiled_graph = build_graph()
