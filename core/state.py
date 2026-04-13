"""LangGraph state type definitions and reducers."""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional
from typing_extensions import TypedDict


# ─── Reducer functions (must be named, not lambdas, for pickling) ────────────

def _merge_dicts(a: Optional[Dict], b: Optional[Dict]) -> Dict:
    """Merge two dicts, with b taking precedence. Handles None."""
    return {**(a or {}), **(b or {})}


def _concat_lists(a: Optional[List], b: Optional[List]) -> List:
    """Concatenate two lists. Handles None."""
    return (a or []) + (b or [])


# ─── Data types used within state ─────────────────────────────────────────────

class Message(TypedDict):
    role: str     # "user" | "assistant" | "system"
    content: str


class AgentTask(TypedDict):
    agent_id: str
    sub_query: str


class RoutingPlan(TypedDict):
    tasks: List[AgentTask]
    execution_mode: str         # "parallel" | "sequential"
    routing_rationale: str


class AgentResult(TypedDict):
    agent_id: str
    status: str                 # "success" | "failed"
    response: str
    tool_executions: List[Dict[str, Any]]   # serialized ToolExecutionResult dicts
    error: Optional[str]


# ─── Main LangGraph state ──────────────────────────────────────────────────────

class OrchestrationState(TypedDict):
    # Inputs
    conversation_history: List[Message]
    current_query: str

    # Set by Send fan-out for each sub-agent branch
    current_agent_task: Optional[AgentTask]

    # Written by coordinator
    routing_plan: Optional[RoutingPlan]

    # Written by sub-agent branches (merged via reducer)
    agent_results: Annotated[Dict[str, AgentResult], _merge_dicts]

    # Written by cross-aggregator
    final_response: str

    # Accumulated across all agents (merged via reducer)
    execution_trace: Annotated[List[Dict[str, Any]], _concat_lists]
    llm_call_log: Annotated[List[Dict[str, Any]], _concat_lists]
