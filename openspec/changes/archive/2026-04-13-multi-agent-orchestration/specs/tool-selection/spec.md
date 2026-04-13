# Spec: Sub-Agent Tool Selection

**Source Requirements**: FR-2.1
**Design Section**: design.md §5.2, §4.3

---

## Purpose

Each sub-agent node begins by calling a high-capability LLM (tool_selector) with the sub-query and the full set of tools available to that agent. The LLM produces a structured `ToolExecutionPlan`: which tools to call, with what initial parameters, and which tools depend on others.

---

## Interfaces

### Input

```
agent_task: AgentTask
  agent_id: str
  sub_query: str
app_context.tool_selector_llm: LLMAdapter
app_context.tool_registry[agent_id]: List[LoadedTool]
  Each LoadedTool has:
    config.id: str
    config.name: str
    config.description: str
    config.input_schema: dict    # JSON Schema
    config.depends_on: List[ToolDependencyConfig]
```

### Output: ToolExecutionPlan

```
ToolExecutionPlan:
  tools: List[PlannedToolCall]
    tool_id: str
    initial_params: dict       # params known before dependency resolution
    depends_on: List[str]      # tool_ids this call depends on (may be empty)
  direct_response: Optional[str]  # set when no tools are needed
```

---

## Detailed Behavior

### Step 1: Build Tool Schema List

For each tool in `tool_registry[agent_id]`:
- Convert `ToolConfig` to `ToolSchema` (name, description, input_schema)
- Include tool's `depends_on` IDs in description so the LLM understands dependency relationships

### Step 2: Construct Tool Selector Prompt

System prompt instructs the LLM to:
1. Analyze the sub-query
2. Select which tools are needed (may be zero, one, or many)
3. For each selected tool: specify the `tool_id` and initial parameters (parameters that can be determined from the query alone — not parameters that depend on another tool's output)
4. Specify dependency relationships: if tool B needs tool A's output, list `"depends_on": ["tool_a_id"]`
5. If no tools are needed, respond with `direct_response` text instead

Structured output schema provided to LLM matches `ToolExecutionPlan`.

### Step 3: Call Tool Selector LLM

- Use `app_context.tool_selector_llm.complete()` with `structured_output_schema`
- Record `LLMCallRecord(role="tool_selector", agent_id=agent_id, ...)` in state

### Step 4: Parse and Validate

- Parse response into `ToolExecutionPlan`
- Validate: all `tool_id` values exist in the agent's tool registry
- Validate: dependency references are valid tool_ids within the plan
- Filter out invalid tool references with warning log

### Step 5: Handle Direct Response

If `ToolExecutionPlan.direct_response` is set (no tools needed):
- Skip tool execution entirely
- Use the `direct_response` string as the intra-agent response
- Still record it as an `AgentResult` with empty `tool_executions`

---

## Boundary Conditions

| Condition | Behavior |
|-----------|----------|
| No tools available for agent | LLM instructed to provide direct_response |
| LLM selects tool not in registry | Filter out with warning; if no valid tools remain, treat as no-tool response |
| LLM returns circular dependency | Detect cycle in dependency graph; raise SubAgentError with detail |
| LLM provides params for a dependent field | Accept as override; dependency resolver will fill in remaining gaps |
| LLM selects all tools when only one is needed | Allow; executor will determine optimal parallelism from dependency graph |

---

## Error Scenarios

| Error | Handling |
|-------|---------|
| Tool selector LLM API error | Raise `SubAgentError`; AgentResult.status = "failed" |
| All selected tool_ids invalid | Treat as direct_response with error note |
| Circular dependency detected | AgentResult.status = "failed", error = "circular tool dependency" |

---

## Logging

- Append `LLMCallRecord(role="tool_selector", ...)` to `state.llm_call_log`
- Log selected tool IDs and dependency graph at DEBUG level
