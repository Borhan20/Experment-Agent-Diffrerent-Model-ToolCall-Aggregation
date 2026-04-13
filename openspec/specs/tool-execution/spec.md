# Spec: Tool Execution Engine

**Source Requirements**: FR-2.2, FR-2.3, FR-2.4, FR-2.5, NFR-1, NFR-5, NFR-6
**Design Section**: design.md §5.3, §7.2

---

## Purpose

The Tool Executor takes a `ToolExecutionPlan` and executes all tools respecting their dependency graph:
- Independent tools run in parallel (asyncio.gather)
- Dependent tools run after their predecessors complete
- Simple parameter mapping between tools is handled programmatically (zero LLM calls)
- Non-trivial transformations fall back to the cheap transformer LLM

---

## Components

### A. Tool Executor (`tools/executor.py`)

Manages the DAG execution loop.

### B. Dependency Resolver (`core/dependency_resolver.py`)

Decides how to populate a tool's input params from a predecessor's output.

---

## Tool Executor: Detailed Algorithm

### Input

```
plan: ToolExecutionPlan
tool_registry: Dict[str, LoadedTool]       # handler functions
transformer_llm: LLMAdapter                # cheap LLM for FR-2.5
```

### Output

```
List[ToolExecutionResult]:
  tool_id: str
  status: "success" | "failed"
  output: Optional[dict]     # raw tool return value
  error: Optional[str]
  execution_mode: "parallel" | "sequential"
  start_time: float
  end_time: float
  used_transformer_llm: bool  # for NFR-6 verification
```

### Algorithm

```
1. Build dependency graph:
   - nodes = set of all tool_ids in plan
   - edges = {tool_id: depends_on_ids} from plan

2. Initialize:
   - completed: Dict[str, dict] = {}  # tool_id → output
   - failed: Set[str] = {}
   - results: List[ToolExecutionResult] = []
   - pending: Set[str] = all tool_ids

3. Loop while pending is not empty:
   a. ready = {t for t in pending if all deps in completed.keys()}
   b. If ready is empty and pending is not empty:
      → Deadlock (dependency cycle or all remaining depend on failed tools)
      → Mark remaining pending tools as failed: "upstream dependency failed"
      → Break

   c. Execute all tools in ready concurrently:
      tasks = [execute_single_tool(t, completed, tool_registry) for t in ready]
      batch_results = await asyncio.gather(*tasks, return_exceptions=True)

   d. For each result in batch_results:
      - If success: add to completed[tool_id], record ToolExecutionResult(mode="parallel" if len(ready)>1 else "sequential")
      - If exception: add to failed, record ToolExecutionResult(status="failed", error=str(e))

   e. Remove ready from pending

4. Return results
```

**Execution mode labeling**:
- If a tool runs in a batch of size > 1: `execution_mode = "parallel"`
- If a tool runs alone (either no deps and only one ready, or sequential step): `execution_mode = "sequential"`

---

## Single Tool Execution

```
async execute_single_tool(tool_id, completed_outputs, tool_registry) -> dict:

1. Get planned params from plan.tools[tool_id].initial_params
2. If tool has depends_on:
   For each dependency dep in tool.depends_on:
     resolved_params = dependency_resolver.resolve(
       upstream_output = completed_outputs[dep.tool_id],
       dependency_config = dep,
       target_input_schema = tool_registry[tool_id].config.input_schema
     )
     Merge resolved_params into params (resolved takes precedence over initial)

3. Call tool_registry[tool_id].handler(**params)
4. Return output dict
```

---

## Dependency Resolver: Detailed Algorithm

### Input

```
upstream_output: dict                  # output from the upstream tool
dependency_config: ToolDependencyConfig
  tool_id: str                         # upstream tool ID
  mappings: List[ToolMappingConfig]
    source_field: str
    target_field: str
target_input_schema: dict              # JSON Schema of the downstream tool
transformer_llm: LLMAdapter
```

### Output

```
resolved_params: dict          # fields ready to merge into downstream tool's input
used_llm: bool                 # True if transformer LLM was invoked
```

### Algorithm

```
resolved = {}
needs_llm = False

For each mapping in dependency_config.mappings:
  source_value = upstream_output.get(mapping.source_field)
  
  If source_value is None:
    → needs_llm = True  (cannot resolve this field programmatically)
    break
  
  target_field_schema = target_input_schema["properties"][mapping.target_field]
  target_type = target_field_schema.get("type")
  
  is_simple = (
    type(source_value) matches target_type  # same primitive type
    AND source_value is not dict/list containing nested logic
  )
  
  If is_simple:
    resolved[mapping.target_field] = source_value
  Else:
    needs_llm = True
    break

If NOT needs_llm:
  return (resolved, used_llm=False)

If needs_llm:
  prompt = build_transformation_prompt(
    upstream_output=upstream_output,
    target_schema=target_input_schema,
    mappings=dependency_config.mappings
  )
  llm_response = await transformer_llm.complete(
    messages=[{role: "user", content: prompt}],
    structured_output_schema=target_input_schema
  )
  resolved = parse_llm_response(llm_response)
  Record LLMCallRecord(role="transformer", ...)
  return (resolved, used_llm=True)
```

### Type Matching Rules

| source_value Python type | target JSON Schema type | is_simple? |
|-------------------------|------------------------|-----------|
| str | "string" | Yes |
| int or float | "number" or "integer" | Yes |
| bool | "boolean" | Yes |
| list (flat) | "array" | Yes |
| dict | "object" | No → LLM |
| str → "number" | type mismatch | No → LLM |
| list → "string" | type mismatch | No → LLM |

### Transformation Prompt Template

```
You are a data transformer. Given the output from an upstream tool and the required input schema for a downstream tool, produce a JSON object that satisfies the schema.

Upstream tool output:
{upstream_output_json}

Target input schema:
{target_input_schema_json}

Field mappings hint:
{mappings_description}

Return ONLY a valid JSON object matching the target schema. No explanation.
```

---

## Error Handling

| Error | Handling |
|-------|---------|
| Tool handler raises exception | Catch, record as failed, continue with other tools |
| Transformer LLM API error | Raise in execute_single_tool, caught by executor, tool marked failed |
| Missing source_field in upstream output | Mark downstream tool failed: "upstream field missing: {field}" |
| Transformer LLM returns invalid JSON | Retry once; if still invalid, mark downstream tool failed |
| All tools in batch fail | Executor records all failures; intra-aggregator receives empty results |

---

## NFR-6 Verification

The `used_transformer_llm` flag in `ToolExecutionResult` allows:
```
zero_llm_calls = all(not r.used_transformer_llm for r in results
                     if r.dependency_was_simple_mapping)
```
This is logged per-turn in the cost summary.

---

## Boundary Conditions

| Condition | Behavior |
|-----------|----------|
| Tool plan has only one tool | Executes alone (execution_mode="sequential") |
| All tools are independent | All run in one parallel batch |
| Tool returns empty dict | Treated as valid output; downstream tools proceed |
| Tool handler is not async | Wrap with `asyncio.to_thread()` so it doesn't block the event loop |
| Tool takes > 30 seconds | asyncio.wait_for timeout → fail with "tool timeout" error |
