"""Streamlit Multi-Agent Orchestrator — main application entry point.

Run with:  streamlit run ui/app.py
"""

from __future__ import annotations

import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict

# Ensure project root is on the path when launched from ui/
_PROJECT_ROOT = str(Path(__file__).parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import streamlit as st
from dotenv import load_dotenv

# Load .env from the project root (explicit path so it works regardless of cwd)
load_dotenv(Path(__file__).parent.parent / ".env")

from ui.components.activity import render_activity_panel
from ui.components.chat import render_chat_history
from ui.components.trace import render_trace_panel
from ui.model_config import PROVIDER_MODELS, get_available_providers
from ui.persistence import clear_history, save_history
from ui.runner import run_orchestration_sync
from ui.session import init_session_state, reset_turn_state


# ─── App-level singleton: AppContext is rebuilt when provider/model selection changes

@st.cache_resource(show_spinner="Initializing agents...")
def _get_app_context(provider: str, high_model: str, low_model: str):
    """Build and cache AppContext for the given provider/model combination."""
    print(f"\n[STARTUP] Provider={provider}, high={high_model}, low={low_model}")
    try:
        from config.loader import load_config
        from config.models import LLMRoleConfig, LLMRolesConfig
        app_config = load_config()
        print(f"[STARTUP] Config OK — {len(app_config.agents)} agent(s) loaded.")
    except Exception as e:
        print(f"[STARTUP ERROR] Config failed: {e}")
        raise

    # Override all LLM roles with the user-selected provider and models
    high_cfg = LLMRoleConfig(provider=provider, model=high_model, temperature=0.0)
    low_cfg = LLMRoleConfig(provider=provider, model=low_model, temperature=0.3)
    xfm_cfg = LLMRoleConfig(provider=provider, model=low_model, temperature=0.0)
    app_config.llm_roles = LLMRolesConfig(
        router=high_cfg,
        tool_selector=high_cfg,
        transformer=xfm_cfg,
        aggregator=low_cfg,
    )

    print("[STARTUP] Initializing LLM adapters and tool registry...")
    try:
        from core.context import build_app_context
        ctx = build_app_context(app_config)
        print("[STARTUP] All adapters and tools ready.\n")
    except Exception as e:
        print(f"[STARTUP ERROR] Adapter initialization failed: {e}")
        raise

    return ctx


# ─── Helper functions (defined before use) ────────────────────────────────────

def _handle_user_input(query: str, app_context) -> None:
    """Start a new orchestration turn for the user's query."""
    st.session_state.conversation_history.append(
        {"role": "user", "content": query}
    )

    reset_turn_state()
    st.session_state.is_processing = True

    q: queue.Queue = queue.Queue()
    st.session_state.status_queue = q

    thread = threading.Thread(
        target=run_orchestration_sync,
        args=(query, list(st.session_state.conversation_history), q, app_context),
        daemon=True,
    )
    thread.start()

    st.rerun()


def _poll_queue() -> None:
    """Drain the status queue and update session state, then rerun if still processing."""
    q: queue.Queue = st.session_state.status_queue
    if q is None:
        st.session_state.is_processing = False
        return

    done = False

    while True:
        try:
            event: Dict[str, Any] = q.get_nowait()
        except queue.Empty:
            break

        event_type = event.get("type")

        if event_type == "agent_started":
            agent_id = event["agent_id"]
            st.session_state.current_status[agent_id] = {
                "name": event.get("agent_name", agent_id),
                "status": "processing",
            }

        elif event_type == "agent_done":
            agent_id = event["agent_id"]
            if agent_id in st.session_state.current_status:
                st.session_state.current_status[agent_id]["status"] = (
                    event.get("status", "done")
                )

        elif event_type == "tool_started":
            pass  # tool activity reflected in trace after completion

        elif event_type == "tool_done":
            pass  # handled via full trace on "done" event

        elif event_type == "streaming_chunk":
            st.session_state.final_response_chunks.append(event.get("chunk", ""))

        elif event_type == "done":
            final_response = event.get("response", "")
            st.session_state.conversation_history.append(
                {"role": "assistant", "content": final_response}
            )
            st.session_state.last_trace = event.get("trace", [])
            st.session_state.last_llm_log = event.get("llm_log", [])
            st.session_state.is_processing = False
            st.session_state.status_queue = None
            # Persist history so it survives page refreshes
            save_history(st.session_state.conversation_history)
            done = True
            break

        elif event_type == "error":
            error_msg = event.get("message", "An unknown error occurred.")
            st.session_state.conversation_history.append(
                {"role": "assistant", "content": f"Sorry, an error occurred: {error_msg}"}
            )
            st.session_state.is_processing = False
            st.session_state.status_queue = None
            # Persist even on error so partial history isn't lost
            save_history(st.session_state.conversation_history)
            done = True
            break

    if not done:
        time.sleep(0.15)
    # Always rerun: during processing to poll again; after done to render the response.
    # Without this, the "done" event updates session state but Streamlit never
    # re-renders, so the user sees "Thinking..." until they manually refresh.
    st.rerun()


# ─── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(
    layout="wide",
    page_title="Multi-Agent Orchestrator",
    page_icon="🤖",
)

# ─── Session state ────────────────────────────────────────────────────────────

init_session_state()

# ─── Sidebar: model selector + agent activity + trace ─────────────────────────

with st.sidebar:
    st.title("🤖 Multi-Agent Orchestrator")
    st.divider()

    # ── Provider / Model selector ──────────────────────────────────────────────
    st.subheader("Model Configuration")

    available_providers = get_available_providers()

    if not available_providers:
        st.error(
            "No API keys detected. Add at least one key to `.env`:\n"
            "- `GOOGLE_API_KEY` for Gemini\n"
            "- `ANTHROPIC_API_KEY` for Claude\n"
            "- `OPENAI_API_KEY` for GPT"
        )
        st.stop()

    provider_display = {pid: PROVIDER_MODELS[pid]["display"] for pid in available_providers}

    selected_provider = st.selectbox(
        "Provider",
        options=available_providers,
        format_func=lambda pid: provider_display[pid],
        key="selected_provider",
    )

    pinfo = PROVIDER_MODELS[selected_provider]

    selected_high_model = st.selectbox(
        "High-capability model",
        options=pinfo["high_models"],
        index=0,
        key=f"high_model_{selected_provider}",
        help="Used for routing and tool selection (accuracy matters most)",
    )

    selected_low_model = st.selectbox(
        "Low-cost model",
        options=pinfo["low_models"],
        index=0,
        key=f"low_model_{selected_provider}",
        help="Used for parameter transformation and result aggregation (cost matters most)",
    )

    st.divider()

    # ── Clear chat ────────────────────────────────────────────────────────────
    if st.button("Clear chat history", use_container_width=True, disabled=st.session_state.is_processing):
        st.session_state.conversation_history = []
        clear_history()
        st.rerun()

    st.divider()
    render_activity_panel()
    st.divider()
    render_trace_panel()

# ─── Load app context (keyed on provider + model selection) ───────────────────

startup_ok = True
startup_error = ""
try:
    app_context = _get_app_context(selected_provider, selected_high_model, selected_low_model)
except Exception as e:
    startup_ok = False
    startup_error = str(e)

if not startup_ok:
    st.error(
        f"**Startup failed.** Check your config and API keys.\n\n```\n{startup_error}\n```"
    )
    st.stop()

# ─── Main chat area ───────────────────────────────────────────────────────────

render_chat_history()

# Poll queue while processing
if st.session_state.is_processing:
    _poll_queue()

# Chat input (disabled while processing)
if not st.session_state.is_processing:
    user_input = st.chat_input("Ask me anything...")
    if user_input:
        _handle_user_input(user_input, app_context)
