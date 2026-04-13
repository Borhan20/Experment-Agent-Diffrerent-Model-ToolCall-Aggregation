"""Orchestration thread runner — bridges background async execution to Streamlit queue."""

from __future__ import annotations

import asyncio
import logging
import queue
from typing import Any, List

from core.context import AppContext
from core.graph import compiled_graph
from core.state import Message, OrchestrationState

logger = logging.getLogger(__name__)


def run_orchestration_sync(
    query: str,
    history: List[Message],
    status_queue: queue.Queue,
    app_context: AppContext,
) -> None:
    """Run the orchestration graph synchronously in a background thread.

    Uses asyncio.run() which creates a fresh event loop, runs the coroutine,
    cancels any remaining tasks, shuts down async generators, and closes the
    loop cleanly. This avoids "Event loop is closed" errors from gRPC clients
    (e.g. Gemini) that bind to the loop they were first called on.

    Args:
        query: The user's current message.
        history: Full conversation history (including the just-added user message).
        status_queue: Thread-safe queue for UI event communication.
        app_context: Initialized application context with LLM adapters and registry.
    """
    try:
        asyncio.run(_run_async(query, history, status_queue, app_context))
    except Exception as e:
        logger.exception("Orchestration thread crashed: %s", e)
        status_queue.put({"type": "error", "message": str(e)})


async def _run_async(
    query: str,
    history: List[Message],
    status_queue: queue.Queue,
    app_context: AppContext,
) -> None:
    """Async orchestration logic — invokes the compiled LangGraph graph."""
    # Build the conversation history passed to the coordinator
    # (exclude the just-added user message as we pass query separately)
    prior_history = [m for m in history if not (m["role"] == "user" and m["content"] == query)]

    initial_state: OrchestrationState = {
        "conversation_history": prior_history,
        "current_query": query,
        "current_agent_task": None,
        "routing_plan": None,
        "agent_results": {},
        "final_response": "",
        "execution_trace": [],
        "llm_call_log": [],
    }

    graph_config: dict[str, Any] = {
        "configurable": {
            "app_context": app_context,
            "status_queue": status_queue,
        }
    }

    result = await compiled_graph.ainvoke(initial_state, config=graph_config)

    final_response = result.get("final_response", "")
    trace = result.get("execution_trace", [])
    llm_log = result.get("llm_call_log", [])

    status_queue.put({
        "type": "done",
        "response": final_response,
        "trace": trace,
        "llm_log": llm_log,
    })
