# Spec: Streamlit Chatbot UI

**Source Requirements**: FR-5.1, FR-5.2, FR-5.3, FR-5.4, DR-1, DR-3
**Design Section**: design.md §8

---

## Purpose

A Streamlit-based chat interface that displays message history, shows real-time agent and tool activity during processing, streams the final response, and renders a tool execution trace after each turn.

---

## Files

```
ui/
├── app.py           # Entry point: streamlit run ui/app.py
├── session.py       # Session state initialization
└── components/
    ├── chat.py      # Chat bubble rendering
    ├── activity.py  # Agent status indicators
    └── trace.py     # Tool execution trace display
```

---

## Session State Schema (`ui/session.py`)

All state lives in `st.session_state`. Initialized once on first load:

```python
defaults = {
    "conversation_history": [],      # List[Message]
    "current_status": {},            # Dict[agent_id → StatusEntry]
    "last_trace": [],                # List[ToolExecution] from last turn
    "last_llm_log": [],             # List[LLMCallRecord] from last turn
    "is_processing": False,          # bool: blocks input during processing
    "final_response_chunks": [],     # List[str]: accumulated stream chunks
}
```

---

## App Layout (`ui/app.py`)

```python
st.set_page_config(layout="wide", page_title="Multi-Agent Orchestrator")

# Sidebar: agent activity + tool trace
with st.sidebar:
    render_activity_panel()   # components/activity.py
    render_trace_panel()      # components/trace.py

# Main: chat
render_chat_history()         # components/chat.py

# Input
if not st.session_state.is_processing:
    user_input = st.chat_input("Ask me anything...")
    if user_input:
        handle_user_input(user_input)
```

---

## Turn Execution Flow

### `handle_user_input(query: str)`

```python
1. Append {role: "user", content: query} to conversation_history
2. Set is_processing = True
3. Clear current_status, last_trace
4. Create status_queue = queue.Queue()
5. Start thread: threading.Thread(
     target=run_orchestration_sync,
     args=(query, conversation_history, status_queue, app_context)
   ).start()
6. Enter polling loop (st.rerun() based):
   - Read all events from status_queue (non-blocking: queue.get_nowait)
   - Process each event (see Event Types)
   - st.rerun() to refresh UI
   - Stop polling when "done" or "error" event received
7. Append {role: "assistant", content: final_response} to conversation_history
8. Set is_processing = False
9. st.rerun() final render
```

### `run_orchestration_sync(query, history, queue, app_context)`

This runs in a background thread. It:
1. Creates a new asyncio event loop: `loop = asyncio.new_event_loop()`
2. Runs: `loop.run_until_complete(run_orchestration_async(...))`
3. The async function calls the LangGraph graph, passing `queue` for status events
4. On completion, puts `{"type": "done", "response": final_response, "trace": ..., "llm_log": ...}` on queue
5. On exception: puts `{"type": "error", "message": str(e)}` on queue

---

## Status Event Protocol

Events are dicts pushed to the `queue.Queue` by the orchestration layer.

| Event type | Fields | Trigger |
|-----------|--------|---------|
| `agent_started` | `agent_id`, `agent_name` | Sub-agent node begins |
| `tool_started` | `agent_id`, `tool_id`, `tool_name`, `mode` | Tool execution begins |
| `tool_done` | `agent_id`, `tool_id`, `status`, `duration_ms` | Tool completes |
| `agent_done` | `agent_id`, `status` | Sub-agent node completes |
| `streaming_chunk` | `chunk` (str) | Aggregation LLM yields a token |
| `done` | `response`, `trace`, `llm_log` | Entire turn complete |
| `error` | `message` | Unhandled exception in orchestration |

---

## Component Specs

### Chat Display (`components/chat.py`)

```python
def render_chat_history():
    for msg in st.session_state.conversation_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
    
    # If currently streaming, show a live placeholder
    if st.session_state.is_processing:
        with st.chat_message("assistant"):
            response_so_far = "".join(st.session_state.final_response_chunks)
            if response_so_far:
                st.markdown(response_so_far)
            else:
                st.markdown("_Thinking..._")
```

### Agent Activity Indicators (`components/activity.py`)

```python
def render_activity_panel():
    st.subheader("Agent Activity")
    for agent_id, status_entry in st.session_state.current_status.items():
        col1, col2 = st.columns([3, 1])
        col1.write(status_entry["name"])
        if status_entry["status"] == "processing":
            col2.write("⠋")   # or st.spinner equivalent
        elif status_entry["status"] == "done":
            col2.write("✓")
        elif status_entry["status"] == "failed":
            col2.write("✗")
```

### Tool Execution Trace (`components/trace.py`)

```python
def render_trace_panel():
    if not st.session_state.last_trace:
        return
    st.subheader("Tool Execution Trace")
    # Group by agent
    by_agent = group_by_agent(st.session_state.last_trace)
    for agent_id, executions in by_agent.items():
        with st.expander(f"[{agent_id}]", expanded=True):
            for ex in executions:
                mode_icon = "⇉" if ex.execution_mode == "parallel" else "→"
                status_icon = "✓" if ex.status == "success" else "✗"
                duration = f"{(ex.end_time - ex.start_time)*1000:.0f}ms"
                st.write(f"{mode_icon} `{ex.tool_id}` {status_icon} ({duration})")
                if ex.status == "failed":
                    st.caption(f"Error: {ex.error}")
```

---

## Streaming Integration

When the cross-aggregation LLM call uses `stream()`, the orchestration thread:
1. Iterates the async generator inside `loop.run_until_complete()`
2. For each chunk: `status_queue.put({"type": "streaming_chunk", "chunk": chunk})`

The Streamlit polling loop:
1. Reads `streaming_chunk` events from queue
2. Appends each chunk to `st.session_state.final_response_chunks`
3. Calls `st.rerun()` to re-render with accumulated text

**Fallback**: If the provider does not support streaming (or streaming fails), the orchestration falls back to non-streaming `complete()` and sends a single `streaming_chunk` event with the full response.

---

## Boundary Conditions

| Condition | Behavior |
|-----------|----------|
| User submits empty string | `st.chat_input` returns None; no action taken |
| User submits while processing | Input disabled (`is_processing = True`); UI shows "Processing..." |
| Very long response (>10k chars) | Rendered with `st.markdown`; Streamlit handles scrolling |
| No agents dispatched (coordinator error) | Error event → show error message in chat as assistant bubble |
| Sidebar has no trace (first load or error) | Sidebar sections render empty with placeholder text |

---

## Error Display

If an `"error"` event is received:
```python
st.session_state.conversation_history.append({
    "role": "assistant",
    "content": f"Sorry, an error occurred: {event['message']}"
})
st.session_state.is_processing = False
```
