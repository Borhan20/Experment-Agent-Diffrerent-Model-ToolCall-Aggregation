"""Agent activity indicators component."""

from __future__ import annotations

import streamlit as st


_STATUS_ICON = {
    "processing": "⠋",
    "done": "✓",
    "failed": "✗",
}


def render_activity_panel() -> None:
    """Render per-agent status indicators in the sidebar.

    Shows each active agent with a status icon. Empty when no
    orchestration has run yet.
    """
    st.subheader("Agent Activity")

    current_status = st.session_state.get("current_status", {})
    if not current_status:
        if st.session_state.get("is_processing"):
            st.caption("Routing query...")
        else:
            st.caption("No agents active")
        return

    for agent_id, entry in current_status.items():
        col1, col2 = st.columns([4, 1])
        col1.write(entry.get("name", agent_id))
        icon = _STATUS_ICON.get(entry.get("status", ""), "?")
        col2.write(icon)
