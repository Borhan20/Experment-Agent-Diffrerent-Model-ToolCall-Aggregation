# Design: Intelligent Multi-Agent Orchestration System

---

## 1. Architecture Overview

### Pattern: Single-Process Modular Monolith

**Choice**: A single Python process with strict internal module boundaries.

**Rationale**: The requirements mandate LangGraph (a single-process graph engine) and Streamlit (a single-process server). Microservices would add network hops and deployment complexity that exceed the project's scope. Module boundaries enforce separation-of-concerns without distributed system overhead.

### Component Map

```
┌─────────────────────────────────────────────────────────────────┐
│  Streamlit UI (ui/)                                             │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐   │
│  │ Chat Display │ │ Agent Status │ │ Tool Execution Trace │   │
│  └──────────────┘ └──────────────┘ └──────────────────────┘   │
│          │ (queue.Queue events)                                 │
├──────────┼──────────────────────────────────────────────────────┤
│  Core Orchestration (core/)                                     │
│  ┌────────────────────────────────────────────────────┐        │
│  │  LangGraph Main Graph                              │        │
│  │                                                    │        │
│  │  [START] → [Coordinator] → Send(×N) → [SubAgent]  │        │
│  │                                ↓ (fan-in)          │        │
│  │                        [CrossAggregator] → [END]   │        │
│  └────────────────────────────────────────────────────┘        │
│          │                         │                            │
│  ┌───────────────┐     ┌───────────────────────┐               │
│  │ Coordinator   │     │   Sub-Agent Node      │               │
│  │ Node          │     │ ┌──────────────────┐  │               │
│  │               │     │ │ Tool Selector    │  │               │
│  │ (high LLM)    │     │ │ (high LLM)       │  │               │
│  └───────────────┘     │ ├──────────────────┤  │               │
│                         │ │ Tool Executor    │  │               │
│                         │ │ (async parallel/ │  │               │
│                         │ │  sequential)     │  │               │
│                         │ ├──────────────────┤  │               │
│                         │ │ Dep. Resolver    │  │               │
│                         │ │ (programmatic /  │  │               │
│                         │ │  cheap LLM)      │  │               │
│                         │ ├──────────────────┤  │               │
│                         │ │ Intra Aggregator │  │               │
│                         │ │ (cheap LLM)      │  │               │
│                         │ └──────────────────┘  │               │
│                         └───────────────────────┘               │
├─────────────────────────────────────────────────────────────────┤
│  LLM Layer (llm/)                                               │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐            │
│  │ OpenAI       │ │ Anthropic    │ │ Gemini       │            │
│  │ Adapter      │ │ Adapter      │ │ Adapter      │            │
│  └──────────────┘ └──────────────┘ └──────────────┘            │
│        ↑ LLMAdapter Protocol (llm/base.py)                      │
│        │ LLMFactory (llm/factory.py)                            │
├─────────────────────────────────────────────────────────────────┤
│  Tool Layer (tools/)                                            │
│  ┌──────────────────┐ ┌──────────────────────────┐             │
│  │ Tool Registry    │ │ Tool Executor             │             │
│  │ (dynamic import) │ │ (asyncio.gather / chain)  │             │
│  └──────────────────┘ └──────────────────────────┘             │
├─────────────────────────────────────────────────────────────────┤
│  Config Layer (config/)                                         │
│  ┌──────────────────────────────────────────────────┐          │
│  │ agents.yaml  +  settings.yaml  →  Pydantic models │         │
│  └──────────────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Technology Stack

| Layer | Technology | Version Constraint | Justification |
|-------|-----------|-------------------|---------------|
| Orchestration | `langgraph` | `>=0.2,<1.0` | Required by client; provides parallel Send API |
| LLM framework | `langchain-core` | `>=0.3,<1.0` | Required by LangGraph; message types, structured output |
| OpenAI client | `openai` | `>=1.30,<2.0` | Official SDK; supports function-calling and streaming |
| Anthropic client | `anthropic` | `>=0.30,<1.0` | Official SDK; tool_use + streaming support |
| Google Gemini | `google-generativeai` | `>=0.7,<1.0` | Official SDK; function-calling support |
| UI | `streamlit` | `>=1.35,<2.0` | Required by client |
| Config validation | `pydantic` | `>=2.0,<3.0` | V2 for model validation + descriptive errors |
| Config format | YAML (`pyyaml`) | `>=6.0` | Human-readable; sufficient for config complexity |
| Async | `asyncio` (stdlib) | Python 3.11+ | Parallel tool execution within sub-agents |
| Environment | `python-dotenv` | `>=1.0` | .env file loading for API keys |
| Testing | `pytest`, `pytest-asyncio` | latest | Async test support |

**Python version**: 3.11+ (required for `asyncio` task groups, `tomllib`, improved typing).

---

## 3. Directory Structure

```
project-root/
├── config/
│   ├── settings.yaml          # LLM role assignments
│   ├── agents.yaml            # Agent + tool definitions
│   ├── models.py              # Pydantic config models
│   └── loader.py              # YAML loading + validation entry point
├── core/
│   ├── state.py               # LangGraph TypedDict state definitions
│   ├── graph.py               # Main graph: nodes, edges, Send fan-out
│   ├── coordinator.py         # Coordinator node implementation
│   ├── sub_agent.py           # Sub-agent node (reusable for all agents)
│   ├── aggregator.py          # Cross-agent aggregation node
│   └── dependency_resolver.py # Programmatic + LLM-assisted parameter mapping
├── llm/
│   ├── base.py                # LLMAdapter Protocol, LLMResponse, LLMCallRecord
│   ├── factory.py             # get_adapter(role_config) -> LLMAdapter
│   ├── openai_adapter.py      # OpenAI implementation
│   ├── anthropic_adapter.py   # Anthropic implementation
│   └── gemini_adapter.py      # Gemini implementation
├── tools/
│   ├── registry.py            # Dynamic tool loading from config
│   └── executor.py            # Parallel/sequential tool execution engine
├── demo/
│   └── tools/
│       ├── weather.py         # Weather tool handlers (mock)
│       ├── news.py            # News tool handlers (mock)
│       └── calculator.py      # Calculator tool handlers
├── ui/
│   ├── app.py                 # Streamlit entry point
│   ├── session.py             # Session state initialization
│   └── components/
│       ├── chat.py            # Chat bubble rendering
│       ├── activity.py        # Agent status indicators
│       └── trace.py           # Tool execution trace panel
├── tests/
│   ├── unit/
│   │   ├── test_dependency_resolver.py
│   │   ├── test_tool_executor.py
│   │   └── test_config_loader.py
│   └── integration/
│       └── test_end_to_end.py
├── .env.example
├── requirements.txt
└── README.md
```

---

## 4. Data Models

### 4.1 Configuration Models (`config/models.py`)

```
LLMRoleConfig:
  provider: str          # "openai" | "anthropic" | "gemini"
  model: str             # e.g., "claude-opus-4-6"
  temperature: float     # default 0.0

ToolMappingConfig:
  source_field: str      # output field name from upstream tool
  target_field: str      # input field name for this tool

ToolDependencyConfig:
  tool_id: str           # upstream tool ID
  mappings: List[ToolMappingConfig]

ToolConfig:
  id: str
  name: str
  description: str
  handler: str           # dotted module path, e.g., "demo.tools.weather.get_weather"
  input_schema: dict     # JSON Schema object
  output_schema: dict    # JSON Schema object
  depends_on: List[ToolDependencyConfig]  # optional

AgentConfig:
  id: str
  name: str
  description: str
  tools: List[ToolConfig]

AppConfig:
  llm_roles:
    router: LLMRoleConfig
    tool_selector: LLMRoleConfig
    transformer: LLMRoleConfig
    aggregator: LLMRoleConfig
  agents: List[AgentConfig]
```

### 4.2 LangGraph State (`core/state.py`)

```
Message:
  role: "user" | "assistant" | "system"
  content: str

AgentTask:
  agent_id: str
  sub_query: str

RoutingPlan:
  tasks: List[AgentTask]
  execution_mode: "parallel" | "sequential"
  routing_rationale: str  # for logging

ToolExecution:
  tool_id: str
  agent_id: str
  status: "pending" | "running" | "success" | "failed"
  execution_mode: "parallel" | "sequential"
  start_time: float        # Unix timestamp
  end_time: Optional[float]
  input_params: dict       # sanitized
  output_summary: str      # truncated for display
  error: Optional[str]

LLMCallRecord:
  role: "router" | "tool_selector" | "transformer" | "aggregator"
  provider: str
  model: str
  input_tokens: int
  output_tokens: int
  timestamp: float

AgentResult:
  agent_id: str
  status: "success" | "failed"
  response: str            # natural language from intra-aggregator
  tool_executions: List[ToolExecution]
  error: Optional[str]

OrchestrationState (TypedDict):
  conversation_history: List[Message]
  current_query: str
  routing_plan: Optional[RoutingPlan]
  agent_results: Dict[str, AgentResult]  # keyed by agent_id
  final_response: str
  execution_trace: List[ToolExecution]   # flattened across all agents
  llm_call_log: List[LLMCallRecord]
  status_events: List[StatusEvent]       # for UI queue
```

### 4.3 LLM Layer Types (`llm/base.py`)

```
ToolSchema:
  name: str
  description: str
  input_schema: dict  # JSON Schema

LLMResponse:
  content: str
  tool_calls: Optional[List[ToolCall]]
  input_tokens: int
  output_tokens: int
  model: str

ToolCall:
  tool_name: str
  arguments: dict

LLMAdapter (Protocol):
  async def complete(
    messages: List[Message],
    tools: Optional[List[ToolSchema]] = None,
    structured_output_schema: Optional[dict] = None
  ) -> LLMResponse

  async def stream(
    messages: List[Message]
  ) -> AsyncIterator[str]
```

---

## 5. LangGraph Graph Design

### 5.1 Main Graph (`core/graph.py`)

The graph uses LangGraph's `Send` API for dynamic parallel fan-out:

```
Nodes:
  - coordinator      : CoordinatorNode
  - run_sub_agent    : SubAgentNode  (reused for all agents via Send)
  - cross_aggregator : CrossAggregatorNode

Edges:
  START → coordinator
  coordinator → run_sub_agent  (via conditional edge that returns List[Send])
  run_sub_agent → cross_aggregator  (fan-in: waits for all Sends to complete)
  cross_aggregator → END

Fan-out mechanism:
  The coordinator edge function reads routing_plan.tasks and returns:
    [Send("run_sub_agent", {agent_task: task_1, ...state}),
     Send("run_sub_agent", {agent_task: task_2, ...state}),
     ...]
  LangGraph executes all Sends in parallel and merges results before
  the cross_aggregator node.

State merge:
  agent_results is Dict[str, AgentResult]. Each sub-agent branch writes
  to its own key (agent_id). No write conflicts.
```

### 5.2 Sub-Agent Execution Flow

Within each `SubAgentNode` invocation (a single Python async function):

```
1. Receive: agent_id, sub_query, tool configs for this agent
2. Build tool schema list from tool registry
3. Call high-capability LLM (tool_selector) with sub_query + tool schemas
   → returns ToolExecutionPlan {tools: [{tool_id, params, depends_on}], direct_response: Optional[str]}
   *If no tools are applicable, the LLM falls back to its own knowledge to provide an interactive `direct_response`.*
4. If tools exist in plan:
   a. Build dependency DAG from ToolExecutionPlan
   b. Execute tools: run parallel batches, resolve dependencies, repeat until done
   c. Call cheap LLM (aggregator) with sub_query + all tool results → response string
5. If no tools exist:
   a. Use `direct_response` as the response string
6. Return AgentResult
```

### 5.3 Dependency Resolver Logic (`core/dependency_resolver.py`)

```
Input: upstream_tool_output: dict, dependency_config: ToolDependencyConfig, target_input_schema: dict

Algorithm:
  1. For each mapping in dependency_config.mappings:
     - source_value = upstream_output[source_field]
     - target_type  = target_input_schema["properties"][target_field]["type"]
     - if type(source_value) matches target_type: record as programmatic mapping
     - else: mark as needs_transformation = True

  2. If all mappings are programmatic:
     - Build target_params dict by applying mappings
     - Return (target_params, used_llm=False)

  3. If any mapping needs_transformation:
     - Call cheap LLM (transformer) with:
       * Upstream tool output (JSON)
       * Target tool input schema
       * Instruction: "Transform the upstream output to match the target schema"
     - Parse LLM response as JSON matching target schema
     - Return (target_params, used_llm=True)

  4. Merge with any already-known params (from tool_selector's initial plan)
     - Dependency-resolved params take precedence
```

---

## 6. LLM Adapter Design

### 6.1 Adapter Interface

All three providers implement the same `LLMAdapter` Protocol. The key behavioral contract:

- `complete()` with `tools` parameter → uses provider's function-calling mode
- `complete()` with `structured_output_schema` → uses JSON mode / guided generation
- `stream()` → returns async generator of string chunks
- All methods record token usage and return `LLMResponse`

### 6.2 Provider-Specific Behaviors

| Feature | OpenAI | Anthropic | Gemini |
|---------|--------|-----------|--------|
| Function calling | `tools` param + `tool_choice` | `tools` param + `tool_use` blocks | `tools` param + function declarations |
| Structured JSON output | `response_format: {type: "json_schema"}` | Prompt + `tool_use` trick or beta JSON mode | `response_mime_type: "application/json"` |
| Streaming | `stream=True` → iterate chunks | `stream=True` → iterate events | `generate_content_async` with streaming |
| Token counting | `usage.prompt_tokens` / `completion_tokens` | `usage.input_tokens` / `output_tokens` | `usage_metadata.prompt_token_count` |

### 6.3 Factory Pattern

```
LLMFactory.get_adapter(role_config: LLMRoleConfig) -> LLMAdapter:
  provider map:
    "openai"    → OpenAIAdapter(model, temperature)
    "anthropic" → AnthropicAdapter(model, temperature)
    "gemini"    → GeminiAdapter(model, temperature)
  Raises ValueError for unknown provider (caught at startup)

Role adapters initialized once at app startup, stored in AppContext:
  app_context.router_llm
  app_context.tool_selector_llm
  app_context.transformer_llm
  app_context.aggregator_llm
```

---

## 7. Tool Registry & Execution

### 7.1 Tool Registry (`tools/registry.py`)

Dynamic tool loading at startup:

```
For each AgentConfig in app_config.agents:
  For each ToolConfig in agent.tools:
    module_path, func_name = tool_config.handler.rsplit(".", 1)
    module = importlib.import_module(module_path)
    handler_fn = getattr(module, func_name)
    registry[agent_id][tool_id] = LoadedTool(config=tool_config, handler=handler_fn)
```

Tool handlers are plain Python async functions with signature:
```
async def tool_handler(**kwargs) -> dict
```

### 7.2 Tool Executor (`tools/executor.py`)

Builds and executes a DAG:

```
Input: List[PlannedToolCall], loaded_tools: Dict[str, LoadedTool]

1. Build adjacency list from depends_on relationships
2. Find root tools (no dependencies) → initial ready_set
3. Execute ready_set via asyncio.gather
4. For each completed tool:
   a. Record ToolExecution result
   b. Find tools that depended on this tool
   c. For each such tool: resolve parameters via DependencyResolver
   d. If all of tool's dependencies are now resolved: add to ready_set
5. Loop until ready_set is empty and all tools complete
6. Return List[ToolExecutionResult]
```

**Error handling within executor**:
- Tool raises exception → ToolExecution.status = "failed", error captured
- Downstream tools that depend on failed tool → also marked failed, not executed
- Other independent tools → continue executing

---

## 8. Streamlit UI Design

### 8.1 Session State Schema (`ui/session.py`)

```python
st.session_state:
  conversation_history: List[Message]     # persists across turns
  current_status: Dict[str, str]          # agent_id → "processing"|"done"|"failed"
  last_trace: List[ToolExecution]         # trace from last turn
  last_llm_log: List[LLMCallRecord]       # LLM calls from last turn
  status_queue: queue.Queue               # cross-thread event channel
```

### 8.2 Turn Execution Flow

```
1. User submits message via st.chat_input
2. Append user message to conversation_history
3. Display user bubble immediately
4. Create queue.Queue() for status events
5. Start thread: run_orchestration(query, history, queue)
6. Show status container with st.empty() placeholders
7. Poll queue in Streamlit rerun loop:
   - "agent_started" event → update activity indicator to spinner
   - "tool_started" event  → update tool trace
   - "tool_done" event     → update tool status
   - "agent_done" event    → update activity indicator to checkmark
   - "streaming_chunk" event → append to response placeholder
   - "done" event          → finalize, re-render chat
8. Thread completes → queue sends "done" with final response + trace
9. Append assistant message to conversation_history
10. Re-render full chat history
```

### 8.3 Streaming Integration

The final cross-aggregation LLM call uses `adapter.stream()`. The orchestration thread iterates the async generator in a sync wrapper (`asyncio.run` in thread), pushing each chunk as a `"streaming_chunk"` event to the queue. The UI polls and appends chunks to a `st.empty()` placeholder.

### 8.4 UI Layout

```
┌────────────────────────────────────────────────────┐
│ [Sidebar]                                          │
│  Agent Activity:                                   │
│  ⠋ Weather Agent  (processing)                    │
│  ✓ News Agent     (done)                           │
│                                                    │
│  Tool Execution Trace:                             │
│  [weather_agent]                                   │
│    → get_current_weather  ✓  (parallel)  142ms    │
│    → get_forecast         ✓  (sequential) 89ms    │
│  [news_agent]                                      │
│    → search_news    ✓  (parallel)  201ms           │
│    → summarize      ✓  (sequential) 310ms          │
├────────────────────────────────────────────────────┤
│ [Main Area]                                        │
│  🧑 User: What's the weather...                    │
│  🤖 Assistant: The weather in Dhaka is...          │
│                                                    │
│  [chat input box]                                  │
└────────────────────────────────────────────────────┘
```

---

## 9. Configuration Schema

### `config/settings.yaml`

```yaml
llm_roles:
  router:
    provider: anthropic
    model: claude-opus-4-6
    temperature: 0.0
  tool_selector:
    provider: anthropic
    model: claude-opus-4-6
    temperature: 0.0
  transformer:
    provider: anthropic
    model: claude-haiku-4-5-20251001
    temperature: 0.0
  aggregator:
    provider: anthropic
    model: claude-haiku-4-5-20251001
    temperature: 0.3
```

### `config/agents.yaml` (excerpt)

```yaml
agents:
  - id: weather_agent
    name: Weather Agent
    description: >
      Handles weather-related queries. Can retrieve current conditions
      and multi-day forecasts for any location.
    tools:
      - id: get_current_weather
        name: Get Current Weather
        description: Returns current weather conditions for a location
        handler: demo.tools.weather.get_current_weather
        input_schema:
          type: object
          properties:
            location: {type: string, description: "City name or coordinates"}
          required: [location]
        output_schema:
          type: object
          properties:
            location: {type: string}
            temperature_c: {type: number}
            condition: {type: string}
            humidity_pct: {type: number}

      - id: get_weather_forecast
        name: Get Weather Forecast
        description: Returns 3-day weather forecast. Requires location from current weather.
        handler: demo.tools.weather.get_weather_forecast
        input_schema:
          type: object
          properties:
            location: {type: string}
            days: {type: integer, default: 3}
          required: [location]
        output_schema:
          type: object
          properties:
            forecasts: {type: array}
        depends_on:
          - tool_id: get_current_weather
            mappings:
              - source_field: location
                target_field: location

  - id: news_agent
    name: News Agent
    description: >
      Handles news and current events queries. Searches and summarizes articles.
    tools:
      - id: search_news
        name: Search News
        description: Searches for recent news articles on a topic
        handler: demo.tools.news.search_news
        input_schema:
          type: object
          properties:
            query: {type: string}
            max_results: {type: integer, default: 5}
          required: [query]
        output_schema:
          type: object
          properties:
            articles: {type: array, items: {type: object}}

      - id: summarize_articles
        name: Summarize Articles
        description: Summarizes a list of news articles into key points
        handler: demo.tools.news.summarize_articles
        input_schema:
          type: object
          properties:
            articles: {type: array}
          required: [articles]
        output_schema:
          type: object
          properties:
            summary: {type: string}
        depends_on:
          - tool_id: search_news
            mappings:
              - source_field: articles
                target_field: articles

  - id: calculator_agent
    name: Calculator Agent
    description: >
      Handles mathematical computations and unit conversions.
    tools:
      - id: calculate
        name: Calculate
        description: Evaluates a mathematical expression
        handler: demo.tools.calculator.calculate
        input_schema:
          type: object
          properties:
            expression: {type: string}
          required: [expression]
        output_schema:
          type: object
          properties:
            result: {type: number}
            expression: {type: string}
```

---

## 10. Security Design

**API Key Management**:
- All keys read from environment variables at startup via `os.environ`
- `.env.example` documents required variable names
- Keys never serialized to state, logs, or config files
- LLM call logs record model/token metadata only — never prompt content containing keys

**Input Sanitization for Logs**:
- Tool inputs logged with sanitized copy: any field matching patterns `*key*`, `*secret*`, `*token*`, `*password*` is redacted before storing in `ToolExecution.input_params`

**No Auth in Scope**:
- Streamlit app runs locally; no multi-user auth needed per scope

**Prompt Injection Mitigation**:
- Tool outputs passed to LLMs are wrapped in structured JSON — they are in the `data` role, not the `system` role
- Tool output strings are truncated to 4000 chars before being passed to aggregation LLM to prevent context stuffing

---

## 11. Infrastructure & Observability

**Runtime**: Local Python process. `streamlit run ui/app.py`

**Environment files**:
- `.env.example` — template with all required env vars
- `.env` — user's actual keys (gitignored)

**Startup validation sequence**:
1. Load `.env`
2. Load and validate `config/settings.yaml` → Pydantic parse
3. Load and validate `config/agents.yaml` → Pydantic parse
4. Validate all tool `handler` dotted paths are importable
5. Initialize LLM adapters for all 4 roles
6. Validate API keys exist for configured providers (check env vars present, not valid)
7. Start Streamlit

**LLM Call Observability** (NFR-4):
Each LLM call appends to `state.llm_call_log`. At end of turn, log summary is printed to stdout:
```
[TURN COST SUMMARY]
  router       | anthropic/claude-opus-4-6         | in:512  out:48   | ~$0.003
  tool_sel×2   | anthropic/claude-opus-4-6         | in:1024 out:128  | ~$0.008
  aggregator×3 | anthropic/claude-haiku-4-5-20251001 | in:2048 out:256 | ~$0.001
  TOTAL estimated: ~$0.012
```

---

## 12. Technical Decisions Log

| Decision | Options Considered | Choice | Rationale |
|----------|-------------------|--------|-----------|
| Sub-agent parallelism mechanism | LangGraph parallel edges vs. `Send` API vs. asyncio in single node | LangGraph parallel conditional edges | Provides clear visual mapping of individual agents as distinct nodes in the graph architecture, making the orchestration flow more explicit. Requires registering all agent nodes at graph-build time. |
| Tool-level parallelism | LangGraph sub-graphs vs. asyncio.gather in node | asyncio.gather within sub-agent node | Nested LangGraph graphs add state propagation complexity. Tool execution is I/O-bound; asyncio.gather is ideal and keeps sub-agent as a single cohesive node. |
| LLM adapter pattern | Direct provider SDK calls everywhere vs. Protocol adapter | Protocol adapter | Isolates provider-specific code. Swapping providers (FR-6.3) becomes a config change. Essential for NFR-2. |
| Config format | JSON vs. YAML vs. TOML | YAML | More human-readable than JSON (comments, multi-line strings). More familiar than TOML for Python dev audience. TOML would also work but YAML has broader tooling. |
| Pydantic vs. manual validation | Manual dict access vs. Pydantic v2 | Pydantic v2 | Descriptive error messages for NFR-7. Type safety. `model_validate` from dict is clean. |
| Streamlit threading model | Streamlit `async` support vs. thread + queue | Thread + `queue.Queue` | Streamlit is sync; LangGraph orchestration is async. Running orchestration in a thread with queue-based event passing is the established pattern. Avoids monkey-patching the event loop. |
| Dependency mapping: "simple" threshold | Field-level type checking vs. schema matching vs. structural | Field-level type + name mapping | "Simple mapping" = rename (same type, different name) or pass-through (same name, same type). Any nested extraction or computation is non-simple → cheap LLM. This is implementable and auditable. |
| State merging for parallel agents | Shared mutable dict vs. TypedDict with reducer | TypedDict + LangGraph reducer | LangGraph's reducer functions handle merge of `agent_results` dict safely. Each branch writes its own `agent_id` key — no conflicts. |

---

## 13. Requirement Coverage Matrix

| Requirement | Spec | Design Section |
|-------------|------|----------------|
| FR-1.1, FR-1.2 | specs/coordinator | §5.1, §4.2 |
| FR-2.1 | specs/tool-selection | §5.2, §4.3 |
| FR-2.2, FR-2.3 | specs/tool-execution | §7.2 |
| FR-2.4, FR-2.5 | specs/tool-execution | §5.3, §7.2 |
| FR-3.1, FR-3.2 | specs/aggregation | §5.2, §5.1 |
| FR-4.1 | specs/parallel-dispatch | §5.1, §12 |
| FR-5.1–5.4 | specs/ui | §8 |
| FR-6.1–6.3 | specs/config | §9, §6.3 |
| FR-7.1 | specs/demo | §9 (agents.yaml) |
| NFR-1 | specs/parallel-dispatch | asyncio.gather |
| NFR-2 | specs/config | §6 |
| NFR-3 | specs/config | §7.1 |
| NFR-4 | all specs | §11 |
| NFR-5 | specs/tool-execution, aggregation | §7.2 error handling |
| NFR-6 | specs/tool-execution | §5.3 algorithm |
| NFR-7 | specs/config | §11 startup sequence |
| IR-1–IR-3 | specs/config | §6 |
| IR-4 | all | §5 |
| DR-1–DR-5 | specs/ui, coordinator | §4.2, §8.1 |
s.yaml) |
| NFR-1 | specs/parallel-dispatch | asyncio.gather |
| NFR-2 | specs/config | §6 |
| NFR-3 | specs/config | §7.1 |
| NFR-4 | all specs | §11 |
| NFR-5 | specs/tool-execution, aggregation | §7.2 error handling |
| NFR-6 | specs/tool-execution | §5.3 algorithm |
| NFR-7 | specs/config | §11 startup sequence |
| IR-1–IR-3 | specs/config | §6 |
| IR-4 | all | §5 |
| DR-1–DR-5 | specs/ui, coordinator | §4.2, §8.1 |
