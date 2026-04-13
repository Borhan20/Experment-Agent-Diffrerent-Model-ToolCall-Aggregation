"""Tool execution trace display component."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

import streamlit as st


def render_trace_panel() -> None:
    """Render the tool execution trace grouped by agent.

    Shows tool name, execution mode (parallel/sequential), status icon,
    and duration for each tool in the last turn. Hidden when no trace exists.
    """
    trace: List[Dict[str, Any]] = st.session_state.get("last_trace", [])
    if not trace:
        return

    st.subheader("Tool Execution Trace")

    # Group by agent_id preserving order of first appearance
    by_agent: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for entry in trace:
        by_agent[entry.get("agent_id", "unknown")].append(entry)

    for agent_id, executions in by_agent.items():
        with st.expander(f"[{agent_id}]", expanded=True):
            for ex in executions:
                mode = ex.get("execution_mode", "sequential")
                status = ex.get("status", "unknown")
                start_t = ex.get("start_time", 0)
                end_t = ex.get("end_time", start_t)
                duration_ms = int((end_t - start_t) * 1000)

                mode_icon = "⇉" if mode == "parallel" else "→"
                status_icon = "✓" if status == "success" else "✗"
                tool_id = ex.get("tool_id", "?")

                st.write(f"{mode_icon} `{tool_id}` {status_icon}  ({duration_ms}ms)")

                if status == "failed" and ex.get("error"):
                    st.caption(f"Error: {ex['error']}")
