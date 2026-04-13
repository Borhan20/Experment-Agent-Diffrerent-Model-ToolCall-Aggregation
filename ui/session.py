"""Streamlit session state initialization and management."""

from __future__ import annotations

import streamlit as st

from ui.persistence import load_history


_TRANSIENT_DEFAULTS = {
    "current_status": {},         # Dict[agent_id → {"name": str, "status": str}]
    "last_trace": [],             # List[ToolExecution dicts] from last turn
    "last_llm_log": [],           # List[LLMCallRecord dicts] from last turn
    "is_processing": False,       # bool: blocks input during orchestration
    "final_response_chunks": [],  # List[str]: streaming chunks accumulator
    "status_queue": None,         # queue.Queue (set when processing starts)
}


def init_session_state() -> None:
    """Initialize all session state keys — only on the very first load of a session.

    Uses a sentinel key (_initialized) so that normal st.rerun() cycles (which
    re-execute this function) do NOT reset processing state.  A full page refresh
    creates a brand-new Streamlit session with an empty st.session_state, so the
    sentinel is absent and we safely reset everything (including clearing any
    in-flight is_processing=True from a previous run).
    """
    if "_initialized" in st.session_state:
        # Normal rerun within the same session — do nothing.
        return

    # First load of this session (new tab, page refresh, server restart).
    st.session_state._initialized = True
    st.session_state.is_processing = False
    st.session_state.status_queue = None
    st.session_state.conversation_history = load_history()
    for key, default in _TRANSIENT_DEFAULTS.items():
        st.session_state[key] = default


def reset_turn_state() -> None:
    """Clear per-turn transient state before starting a new orchestration."""
    st.session_state.current_status = {}
    st.session_state.last_trace = []
    st.session_state.last_llm_log = []
    st.session_state.final_response_chunks = []
    st.session_state.status_queue = None
