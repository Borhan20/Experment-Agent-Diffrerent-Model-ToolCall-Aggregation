"""Main LangGraph graph definition — coordinator → conditional edges → cross-aggregator."""

from __future__ import annotations

import logging
from typing import List, Union
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from core.aggregator import cross_aggregator_node
from core.coordinator import coordinator_node
from core.state import OrchestrationState
from core.sub_agent import create_agent_node
from config.loader import load_config

logger = logging.getLogger(__name__)


def _route_to_agents(state: OrchestrationState) -> Union[List[str], str]:
    """Edge function: fan out to dedicated agent nodes based on routing plan.

    Returns a list of node names — one per AgentTask in the plan.
    LangGraph executes all returned nodes concurrently (parallel fan-out).

    If the coordinator already set final_response (no-agent fallback case),
    route directly to cross_aggregator.
    """
    # If coordinator handled the response directly (no valid agents)
    if state.get("final_response"):
        return "cross_aggregator"

    routing_plan = state.get("routing_plan")
    if not routing_plan or not routing_plan.get("tasks"):
        logger.warning("Empty routing plan — routing to cross_aggregator for fallback")
        return "cross_aggregator"

    target_nodes = [task["agent_id"] for task in routing_plan["tasks"]]
    logger.debug("Fan-out: dispatching %d dedicated sub-agent node(s)", len(target_nodes))
    return target_nodes


def build_graph() -> StateGraph:
    """Build and compile the main orchestration graph.

    Graph structure:
        START → coordinator → [agent_id×N] → cross_aggregator → END

    Returns:
        Compiled LangGraph application ready for ainvoke().
    """
    graph = StateGraph(OrchestrationState)

    graph.add_node("coordinator", coordinator_node)
    
    # Load config to dynamically register dedicated agent nodes
    config = load_config(Path("config/settings.yaml"), Path("config/agents.yaml"))
    agent_ids = [agent.id for agent in config.agents]
    
    for agent_id in agent_ids:
        graph.add_node(agent_id, create_agent_node(agent_id))

    graph.add_node("cross_aggregator", cross_aggregator_node)

    graph.add_edge(START, "coordinator")

    graph.add_conditional_edges(
        "coordinator",
        _route_to_agents,
        agent_ids + ["cross_aggregator"],
    )

    for agent_id in agent_ids:
        graph.add_edge(agent_id, "cross_aggregator")
        
    graph.add_edge("cross_aggregator", END)

    return graph.compile()


# Module-level compiled graph — built once at import time.
# This is re-used for all requests.
compiled_graph = build_graph()
