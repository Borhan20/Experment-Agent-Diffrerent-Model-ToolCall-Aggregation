"""Cross-agent aggregation node and cost summary logging."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from langchain_core.runnables import RunnableConfig

from core.context import AppContext
from core.state import OrchestrationState
from llm.base import LLMCallRecord

logger = logging.getLogger(__name__)

_MAX_AGENT_RESPONSE_CHARS = 4000

# Approximate cost per 1M tokens (USD) — as of April 2026 public pricing
_COST_PER_1M = {
    # Anthropic
    "claude-opus-4-6": {"in": 15.0, "out": 75.0},
    "claude-sonnet-4-6": {"in": 3.0, "out": 15.0},
    "claude-haiku-4-5-20251001": {"in": 0.8, "out": 4.0},
    # OpenAI
    "gpt-4o": {"in": 2.5, "out": 10.0},
    "gpt-4o-mini": {"in": 0.15, "out": 0.6},
    "gpt-4-turbo": {"in": 10.0, "out": 30.0},
    # Gemini
    "gemini-1.5-flash": {"in": 0.075, "out": 0.3},
    "gemini-1.5-pro": {"in": 1.25, "out": 5.0},
    "gemini-2.0-flash": {"in": 0.1, "out": 0.4},
    "gemini-2.0-flash-lite": {"in": 0.075, "out": 0.3},
    "gemini-2.5-pro": {"in": 1.25, "out": 10.0},
    "gemini-2.5-flash": {"in": 0.15, "out": 0.6},
    "gemini-2.5-flash-lite": {"in": 0.1, "out": 0.4},
}


async def cross_aggregator_node(
    state: OrchestrationState,
    config: RunnableConfig,
) -> Dict[str, Any]:
    """LangGraph node: aggregate all sub-agent responses into a final reply.

    Single-agent case: return agent response directly (no LLM call).
    Multi-agent case: call aggregator LLM with streaming.

    Args:
        state: Merged state after all sub-agent branches complete.
        config: LangGraph config with app_context and status_queue.

    Returns:
        Partial state update with final_response and llm_call_log.
    """
    app_context: AppContext = config["configurable"]["app_context"]
    status_queue = config["configurable"].get("status_queue")

    agent_results = state.get("agent_results", {})
    current_query = state.get("current_query", "")
    new_llm_records: List[Dict[str, Any]] = []

    # Remove fallback placeholder if present
    real_results = {k: v for k, v in agent_results.items() if k != "__fallback__"}

    # If coordinator set final_response directly (no-agent fallback)
    if not real_results:
        final = state.get("final_response", "I could not process your query.")
        _print_cost_summary(state.get("llm_call_log", []))
        return {"final_response": final}

    successful = {k: v for k, v in real_results.items() if v["status"] == "success"}
    failed = {k: v for k, v in real_results.items() if v["status"] == "failed"}

    # All agents failed
    if not successful:
        final = "I was unable to process your query at this time."
        _print_cost_summary(state.get("llm_call_log", []))
        return {"final_response": final}

    # Single agent — return directly (no cross-aggregation LLM call)
    if len(real_results) == 1:
        only = list(successful.values())[0] if successful else list(failed.values())[0]
        final = only["response"] or "I was unable to retrieve information for your query."
        _print_cost_summary(state.get("llm_call_log", []))
        return {"final_response": final}

    # Multiple agents — build cross-aggregation prompt
    specialist_parts: List[str] = []
    for agent_id, result in successful.items():
        resp = result["response"][:_MAX_AGENT_RESPONSE_CHARS]
        specialist_parts.append(f"[Agent: {agent_id}]\n{resp}")

    if failed:
        failed_ids = ", ".join(failed.keys())
        specialist_parts.append(f"[Note: Could not retrieve information from: {failed_ids}]")

    specialist_text = "\n\n".join(specialist_parts)
    messages = [
        {
            "role": "system",
            "content": (
                "You are an assistant combining multiple specialized responses into one "
                "coherent answer. Weave together all information naturally. "
                "Do not list agents or mention the routing process."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Original query: {current_query}\n\n"
                f"Specialist responses:\n{specialist_text}\n\n"
                "Provide one unified, helpful response."
            ),
        },
    ]

    # Stream aggregation response to UI queue
    full_response = ""
    try:
        async for chunk in app_context.aggregator_llm.stream(messages):
            full_response += chunk
            if status_queue is not None:
                status_queue.put({"type": "streaming_chunk", "chunk": chunk})
    except Exception as e:
        logger.exception("Aggregation LLM streaming failed: %s", e)
        if full_response:
            full_response += " [response interrupted]"
        else:
            full_response = "Response generation failed. Please try again."

    # Use exact token counts from the adapter if available (populated during stream),
    # falling back to a character-count estimate only when the adapter doesn't expose them.
    agg_llm = app_context.aggregator_llm
    in_tokens = getattr(agg_llm, "_last_stream_input_tokens", None)
    out_tokens = getattr(agg_llm, "_last_stream_output_tokens", None)
    if in_tokens is None:
        in_tokens = len(specialist_text) // 4 + len(current_query) // 4
    if out_tokens is None:
        out_tokens = len(full_response) // 4
    record = LLMCallRecord(
        role="aggregator",
        provider=app_context.app_config.llm_roles.aggregator.provider,
        model=app_context.app_config.llm_roles.aggregator.model,
        input_tokens=in_tokens,
        output_tokens=out_tokens,
        timestamp=time.time(),
    )
    new_llm_records.append(record.to_dict())

    all_records = list(state.get("llm_call_log", [])) + new_llm_records
    _print_cost_summary(all_records)

    return {
        "final_response": full_response,
        "llm_call_log": new_llm_records,
    }


def _print_cost_summary(llm_call_log: List[Dict[str, Any]]) -> None:
    """Print formatted per-turn cost summary to stdout (NFR-4)."""
    if not llm_call_log:
        return

    print("\n[TURN COST SUMMARY]")
    total_cost = 0.0
    for record in llm_call_log:
        model = record.get("model", "unknown")
        pricing = _COST_PER_1M.get(model, {"in": 0.0, "out": 0.0})
        in_tokens = record.get("input_tokens", 0)
        out_tokens = record.get("output_tokens", 0)
        cost = (in_tokens * pricing["in"] + out_tokens * pricing["out"]) / 1_000_000
        total_cost += cost
        print(
            f"  {record.get('role', '?'):<12} | "
            f"{record.get('provider', '?')}/{model:<35} | "
            f"in:{in_tokens:<6} out:{out_tokens:<6} | "
            f"~${cost:.4f}"
        )
    print(f"  {'TOTAL':<12}   {'':40}   ~${total_cost:.4f}\n")
