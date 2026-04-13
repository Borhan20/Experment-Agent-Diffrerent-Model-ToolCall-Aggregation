# Spec: Multi-Agent Parallel Dispatch

**Source Requirements**: FR-4.1, NFR-1
**Design Section**: design.md §5.1, §12 (decision: Send API)

---

## Purpose

When the coordinator produces a routing plan with N agents, all N sub-agents must execute concurrently. LangGraph's `Send` API provides this via dynamic parallel fan-out to a single reusable node.

---

## LangGraph Graph Structure

### Nodes

| Node name | Function | Type |
|-----------|----------|------|
| `coordinator` | CoordinatorNode | Sync/Async Python function |
| `run_sub_agent` | SubAgentNode | Async Python function (reusable) |
| `cross_aggregator` | CrossAggregatorNode | Async Python function |

### Edge Definitions

```python
graph = StateGraph(OrchestrationState)

graph.add_node("coordinator", coordinator_node)
graph.add_node("run_sub_agent", sub_agent_node)
graph.add_node("cross_aggregator", cross_aggregator_node)

graph.add_edge(START, "coordinator")
graph.add_conditional_edges(
    "coordinator",
    route_to_agents,       # returns List[Send]
    ["run_sub_agent"]      # all Sends target this node
)
graph.add_edge("run_sub_agent", "cross_aggregator")
graph.add_edge("cross_aggregator", END)
```

### Send Fan-Out Function

```python
def route_to_agents(state: OrchestrationState) -> List[Send]:
    """
    Called after coordinator_node completes.
    Returns one Send per AgentTask in the routing plan.
    LangGraph executes all Sends concurrently.
    """
    return [
        Send("run_sub_agent", {
            **state,
            "current_agent_task": task
        })
        for task in state.routing_plan.tasks
    ]
```

### State Merge (Fan-In)

LangGraph waits for ALL `run_sub_agent` branches to complete before calling `cross_aggregator`. State is merged using a reducer on `agent_results`:

```python
def merge_agent_results(
    existing: Dict[str, AgentResult],
    new: Dict[str, AgentResult]
) -> Dict[str, AgentResult]:
    return {**existing, **new}
```

Each sub-agent branch writes only its own `agent_id` key — no write conflicts possible.

---

## Concurrency Model

**Within LangGraph**: The `Send` API uses LangGraph's internal async executor. All `run_sub_agent` branches are dispatched as separate async tasks on the same event loop.

**Within each sub-agent branch**: `asyncio.gather` for parallel tool execution (see tool-execution spec).

**Streamlit integration**: The entire graph execution runs in a background thread (not the Streamlit main thread). A `queue.Queue` bridges the thread to the UI. See UI spec.

---

## Performance Guarantee (NFR-1)

The wall-clock time from coordinator completion to cross_aggregator start must be:
```
T_total ≤ max(T_agent_1, T_agent_2, ..., T_agent_N) × 1.1 + 2s
```

The 1.1× factor and 2s fixed overhead account for LangGraph dispatch overhead and inter-task scheduling. This is achievable because:
- All sub-agents start within one asyncio event loop iteration of each other
- No blocking calls in the dispatch path
- Sub-agents do not share any locks or synchronization primitives

---

## Boundary Conditions

| Condition | Behavior |
|-----------|----------|
| Routing plan has 1 task | Single `Send` → effectively sequential, no fan-in merge needed |
| Routing plan has 0 tasks | `route_to_agents` returns `[]` → LangGraph skips to next node; coordinator should not produce empty plans |
| One sub-agent branch crashes with exception | LangGraph catches exception per-branch; other branches continue; cross_aggregator receives AgentResult with status="failed" for the crashed branch |
| Sub-agent takes > 60 seconds | asyncio.wait_for timeout enforced within sub_agent_node; branch completes with status="failed", error="timeout" |

---

## State Isolation

Sub-agent branches must NOT write to shared state fields that other branches also write to. The only field written by sub-agents is `agent_results[agent_id]` — keyed by the unique agent_id. Other state fields (`routing_plan`, `conversation_history`, `current_query`) are read-only within sub-agent branches.

---

## Error Scenarios

| Error | Handling |
|-------|---------|
| `route_to_agents` raises exception | CoordinatorError propagates; graph terminates with error state |
| All sub-agent branches fail | `cross_aggregator` receives all-failed AgentResults; returns degraded response |
| LangGraph Send not supported in installed version | Startup check: import Send from langgraph.constants; raise clear ImportError if missing |
