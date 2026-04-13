# Spec: Result Aggregation

**Source Requirements**: FR-3.1, FR-3.2, NFR-5
**Design Section**: design.md §5.2 (intra), §5.1 (cross)

---

## Purpose

Two-level aggregation:
1. **Intra-agent aggregation** (FR-3.1): each sub-agent aggregates its own tool results into one natural-language response using the cheap LLM.
2. **Cross-agent aggregation** (FR-3.2): the main graph's final node aggregates all sub-agent responses into one unified user-facing response using the cheap LLM.

---

## Intra-Agent Aggregation

### Location

End of `SubAgentNode`, after all tools complete.

### Input

```
sub_query: str
tool_results: List[ToolExecutionResult]
  Each has: tool_id, status, output (dict), error (str)
aggregator_llm: LLMAdapter   # cheap LLM
```

### Output

```
agent_response: str   # natural language, stored in AgentResult.response
```

### Behavior

**Build aggregation prompt**:
```
System: You are an assistant summarizing tool results for a user query.
        Synthesize the results into a single, coherent, conversational response.
        Do not mention tool names or technical details unless directly relevant.

User: Query: {sub_query}

Tool Results:
{for each successful result: tool_id, output summary}
{for each failed result: "Note: {tool_id} was unavailable ({error})"}

Provide a helpful response based on the above results.
```

**Rules**:
- Failed tools are mentioned as "information unavailable" — not hidden silently
- Truncate each tool output to 2000 chars before including in prompt
- If ALL tools failed: response = "I was unable to retrieve the information needed to answer this."
- If zero tools were executed (direct response case): skip aggregation, use `direct_response` from ToolExecutionPlan directly

**LLM call**:
- Use `aggregator_llm.complete()` without tools (pure text generation)
- Record `LLMCallRecord(role="aggregator", ...)` in state

---

## Cross-Agent Aggregation

### Location

`CrossAggregatorNode` — the final node in the main LangGraph graph, after all sub-agent branches complete.

### Input

```
current_query: str
agent_results: Dict[str, AgentResult]   # keyed by agent_id
  Each AgentResult: status, response, error
aggregator_llm: LLMAdapter
```

### Output

```
final_response: str    # written to state.final_response
```

### Behavior

**Single agent case** (routing returned one task):
- Return `agent_results[agent_id].response` directly — do NOT call the LLM
- This avoids an unnecessary LLM call when there's nothing to aggregate

**Multiple agents case**:

Build prompt:
```
System: You are an assistant combining multiple specialized responses into one
        coherent answer. Weave together all information naturally.
        Do not list agents or mention the routing process.

User: Original query: {current_query}

Specialist responses:
[Agent: weather_agent]
{agent_results["weather_agent"].response}

[Agent: news_agent]
{agent_results["news_agent"].response}

{if any agent failed:}
[Note: Some information could not be retrieved: {failed_agent_id}]

Provide one unified, helpful response.
```

- Use `aggregator_llm.stream()` for streaming to UI (see UI spec)
- Record `LLMCallRecord(role="aggregator", ...)` in state
- Write result to `state.final_response`

**Partial failure handling (NFR-5)**:
- Failed agents are included as a note in the prompt
- The LLM is instructed to acknowledge the gap and provide what it can
- System never crashes due to partial failure; always returns a response

---

## Boundary Conditions

| Condition | Behavior |
|-----------|----------|
| Single agent, all tools successful | Return agent response without cross-aggregation LLM call |
| Single agent, all tools failed | Return: "I was unable to retrieve information for your query." |
| Multiple agents, all successful | Cross-aggregation LLM call |
| Multiple agents, one failed | Include failure note in prompt; LLM produces partial response |
| Multiple agents, all failed | Return: "I was unable to process your query at this time." (no LLM call) |
| Agent response is very long (>4000 chars) | Truncate to 4000 chars before cross-aggregation prompt |

---

## Error Scenarios

| Error | Handling |
|-------|---------|
| Aggregator LLM API error (intra) | AgentResult.status = "failed", error = "aggregation failed" |
| Aggregator LLM API error (cross) | state.final_response = "Response generation failed. Please try again." |
| Streaming interrupted mid-response | UI shows partial response; error appended: "[response interrupted]" |
