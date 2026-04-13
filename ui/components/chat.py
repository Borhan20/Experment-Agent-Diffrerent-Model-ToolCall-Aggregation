"""Chat display component — renders conversation history and streaming placeholder."""

from __future__ import annotations

import time

import streamlit as st

# Cycling status phrases — rotate every ~0.6 s so the user sees activity
_THINKING_PHRASES = ["Thinking", "Processing", "Working on it", "Analyzing"]


def _animated_label(base: str) -> str:
    """Return a label with animated trailing dots that cycles across reruns."""
    # Each rerun is ~0.15 s apart; advance the dot count every 0.4 s
    n_dots = (int(time.time() / 0.4) % 3) + 1
    return base + "." * n_dots


def render_chat_history() -> None:
    """Render all messages in conversation history as chat bubbles.

    While processing, shows a live assistant bubble with either:
    - Accumulated streaming chunks (multi-agent cross-aggregation path)
    - An animated typing indicator (while agents/tools are still working)
    """
    for msg in st.session_state.conversation_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if st.session_state.is_processing:
        with st.chat_message("assistant"):
            response_so_far = "".join(st.session_state.final_response_chunks)
            if response_so_far:
                # Streaming chunks arriving — render them progressively
                st.markdown(response_so_far)
            else:
                # Agents still working — show animated status text
                current_status = st.session_state.get("current_status", {})
                active_agents = [
                    info.get("name", aid)
                    for aid, info in current_status.items()
                    if info.get("status") == "processing"
                ]

                if active_agents:
                    base = f"Working with {', '.join(active_agents)}"
                else:
                    # Cycle through phrases while waiting for agents to start
                    phrase_idx = int(time.time() / 1.5) % len(_THINKING_PHRASES)
                    base = _THINKING_PHRASES[phrase_idx]

                st.markdown(f"_{_animated_label(base)}_")
