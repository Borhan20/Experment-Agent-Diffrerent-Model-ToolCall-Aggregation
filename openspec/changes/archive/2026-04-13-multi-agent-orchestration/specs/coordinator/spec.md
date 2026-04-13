# Spec: Coordinator Agent (Router)

**Source Requirements**: FR-1.1, FR-1.2
**Design Section**: design.md §5.1, §4.2

---

## Purpose

The Coordinator is a LangGraph node that receives the user's query and conversation history, calls a high-capability LLM to produce a structured routing plan, and determines which sub-agents should handle the query and with what sub-tasks.

---

## Interfaces

### Input (from LangGraph State)

```
current_query: str               # the user's latest message
conversation_history: List[Message]  # prior turns for context
app_context.router_llm: LLMAdapter   # configured high-capability LLM
app_context.agent_registry: List[AgentConfig]  # available agents
```

### Output (written to LangGraph State)

```
routing_plan: RoutingPlan
  tasks: List[AgentTask]
    agent_id: str          # must match a registered agent ID
    sub_query: str         # the portion of the query this agent handles
  execution_mode: "parallel" | "sequential"
  routing_rationale: str   # logged only, not shown to user
```

---

## Detailed Behavior

### Step 1: Build System Prompt

Construct a system prompt that:
1. Lists all available agents with their `id`, `name`, and `description`
2. Instructs the LLM to return a JSON routing plan
3. Specifies that `execution_mode` should be "parallel" when agents are independent, "sequential" only when one agent's output is required by another

Example system prompt structure:
```
You are a routing coordinator. Given the user's query, select which agents should handle it.

Available agents:
- weather_agent: Handles weather-related queries...
- news_agent: Handles news and current events...
- calculator_agent: Handles mathematical computations...

Return JSON matching this schema:
{
  "tasks": [{"agent_id": "...", "sub_query": "..."}],
  "execution_mode": "parallel" | "sequential",
  "routing_rationale": "..."
}

Rules:
- Select ONLY agents relevant to the query
- If query spans multiple independent domains, set execution_mode to "parallel"
- Assign each agent only the portion of the query relevant to it
- sub_query must be self-contained (the agent won't see the full query)
```

### Step 2: Call Router LLM

- Use `app_context.router_llm.complete()` with `structured_output_schema` = RoutingPlan JSON Schema
- Include conversation history as message context
- Record the LLM call in `state.llm_call_log` with role="router"

### Step 3: Parse and Validate Routing Plan

- Parse the structured response into `RoutingPlan`
- Validate: all `agent_id` values exist in the agent registry
- If an unknown agent ID is returned: log warning, filter out that task
- If zero valid tasks remain after filtering: fall back to single-agent mode — return error response directly

### Step 4: Write to State

- Set `state.routing_plan = routing_plan`
- Push "routing_done" status event to `state.status_events`

---

## LangGraph Edge Function

After the coordinator node, the edge function reads `state.routing_plan.tasks` and returns:

```python
def route_to_agents(state: OrchestrationState) -> List[Send]:
    return [
        Send("run_sub_agent", {**state, "current_agent_task": task})
        for task in state.routing_plan.tasks
    ]
```

This triggers parallel execution of all sub-agent invocations when `execution_mode == "parallel"`. For "sequential" mode (rare), the edge returns `Send` objects in order — but since LangGraph Sends are always async, sequential ordering is approximated; true sequential ordering requires a different graph shape (chain). **Design decision**: default to parallel; sequential cross-agent ordering is deferred to a future enhancement and treated as parallel in the current implementation.

---

## Boundary Conditions

| Condition | Behavior |
|-----------|----------|
| Single-domain query | One AgentTask, execution_mode="parallel" (single agent) |
| Query matches no agent | Return error message: "I don't have a specialized agent for this query." |
| Router LLM returns malformed JSON | Retry once; if still malformed, return generic error |
| Router LLM returns unknown agent_id | Filter out unknown agents, proceed with valid ones |
| Empty query string | Raise ValueError before calling LLM |
| Conversation history > 20 turns | Truncate to last 10 turns (5 user + 5 assistant) before passing to LLM |

---

## Error Scenarios

| Error | Handling |
|-------|---------|
| Router LLM API error (timeout, rate limit) | Raise `CoordinatorError` with message; Streamlit UI shows "Routing failed" |
| Router LLM returns zero agents | Return fallback response: "I could not determine which agent to use." |
| JSON parse failure after retry | Log raw output, return `CoordinatorError` |

---

## Logging

- Log routing_rationale to stdout at DEBUG level
- Append `LLMCallRecord(role="router", ...)` to `state.llm_call_log`
