# Implementation Tasks: Multi-Agent Orchestration System

Tasks are ordered by dependency. Each task is atomic (one focused session).
Format: `- [ ] Description [spec: spec-name] [size: S/M/L]`
Sizes: S = <1hr, M = 1-3hr, L = 3-6hr

---

## Phase 0: Project Foundation

- [x] Create project directory structure: all folders from design.md §3, `requirements.txt`, `.env.example`, `README.md` stub [spec: config] [size: S]
- [x] Write Pydantic config models (`config/models.py`): `LLMRoleConfig`, `ToolMappingConfig`, `ToolDependencyConfig`, `ToolConfig`, `AgentConfig`, `LLMRolesConfig`, `AppConfig` [spec: config] [size: M]
- [x] Write config loader (`config/loader.py`): load + merge settings.yaml + agents.yaml, validate with Pydantic, validate handler importability, validate dependency references, detect cycles, fail fast with descriptive errors [spec: config] [size: M]
- [x] Write `config/settings.yaml` with default LLM role assignments [spec: config] [size: S]
- [x] Write `config/agents.yaml` with all 3 demo agents (weather, news, calculator) and their full tool definitions including depends_on [spec: demo, config] [size: M]

---

## Phase 1: LLM Adapter Layer

- [x] Write LLM base types (`llm/base.py`): `ToolSchema`, `LLMResponse`, `ToolCall`, `LLMCallRecord`, and `LLMAdapter` Protocol with `complete()` and `stream()` signatures [spec: config] [size: S]
- [x] Write OpenAI adapter (`llm/openai_adapter.py`): `complete()` with function-calling support and structured JSON output, `stream()` returning async generator, token usage extraction [spec: config] [size: M]
- [x] Write Anthropic adapter (`llm/anthropic_adapter.py`): `complete()` with `tool_use` blocks and JSON mode, `stream()` with event iteration, token usage from `input_tokens`/`output_tokens` [spec: config] [size: M]
- [x] Write Gemini adapter (`llm/gemini_adapter.py`): `complete()` with function declarations, structured JSON output via `response_mime_type`, `stream()` with async generate, token counting from `usage_metadata` [spec: config] [size: M]
- [x] Write LLM factory (`llm/factory.py`): `get_adapter(role_config)` mapping provider strings to adapter classes, env var presence check per provider [spec: config] [size: S]

---

## Phase 2: Tool Infrastructure

- [x] Write tool registry (`tools/registry.py`): `ToolRegistry` class that loads all handlers via `importlib` at init, stores as `Dict[agent_id][tool_id] → LoadedTool`, provides `get_tool_schemas(agent_id)` returning `List[ToolSchema]` [spec: config] [size: M]
- [x] Write dependency resolver (`core/dependency_resolver.py`): `resolve(upstream_output, dependency_config, target_schema, transformer_llm)` implementing the type-matching algorithm, programmatic mapping path, LLM transformation fallback, returning `(resolved_params, used_llm: bool)` [spec: tool-execution] [size: M]
- [x] Write tool executor (`tools/executor.py`): `execute_tool_plan(plan, tool_registry, transformer_llm)` implementing the DAG execution loop with `asyncio.gather` for parallel batches, dependency resolution between batches, per-tool timeout (30s), exception isolation, returning `List[ToolExecutionResult]` [spec: tool-execution] [size: L]

---

## Phase 3: LangGraph State & Graph

- [x] Write all LangGraph state types (`core/state.py`): `Message`, `AgentTask`, `RoutingPlan`, `ToolExecution`, `LLMCallRecord`, `AgentResult`, `StatusEvent`, `OrchestrationState` TypedDict with reducer for `agent_results` [spec: parallel-dispatch] [size: M]
- [x] Write coordinator node (`core/coordinator.py`): build system prompt with agent registry, call router LLM with structured output schema, parse routing plan, validate agent IDs, push status event, handle retry on malformed JSON, handle zero-agent fallback [spec: coordinator] [size: M]
- [x] Write sub-agent node logic (`core/sub_agent.py`): reusable logic to receive `current_agent_task`, call tool selection, run tool executor, call intra-aggregation, return `AgentResult`, catch all exceptions [spec: tool-selection, aggregation] [size: L]
- [x] Write cross-aggregator node (`core/aggregator.py`): detect single vs. multi-agent case, build cross-agent prompt with successful and failed agent results, call aggregator LLM with streaming, collect chunks and push to status_events, write `final_response` [spec: aggregation] [size: M]
- [x] Wire main LangGraph graph (`core/graph.py`): define distinct nodes per agent (`WeatherAgentNode`, `NewsAgentNode`, `CalculatorAgentNode`), `START → coordinator`, conditional edge `route_to_agents()` returning list of node names, parallel agent nodes → `cross_aggregator`, `cross_aggregator → END`, compile graph [spec: parallel-dispatch] [size: M]

---

## Phase 4: Demo Tool Handlers

- [x] Write weather tools (`demo/tools/weather.py`): `get_current_weather(location)` returning mock weather dict with 0.5s delay; `get_weather_forecast(location, days=3)` returning mock forecast list with 0.3s delay; error trigger on location="FAIL" [spec: demo] [size: S]
- [x] Write news tools (`demo/tools/news.py`): `search_news(query, max_results=5)` returning 5 mock articles with realistic titles based on query; `summarize_articles(articles)` constructing summary from article titles with 0.2s delay [spec: demo] [size: S]
- [x] Write calculator tools (`demo/tools/calculator.py`): `calculate(expression)` using safe AST evaluation returning result dict; `convert_units(value, from_unit, to_unit)` with hardcoded conversion table for temperature/distance/weight [spec: demo] [size: S]

---

## Phase 5: Streamlit UI

- [x] Write session state manager (`ui/session.py`): `init_session_state()` initializing all keys with defaults, `reset_turn_state()` clearing per-turn fields [spec: ui] [size: S]
- [x] Write chat component (`ui/components/chat.py`): `render_chat_history()` rendering all historical messages, handling streaming placeholder during processing [spec: ui] [size: S]
- [x] Write activity component (`ui/components/activity.py`): `render_activity_panel()` reading `current_status` and rendering per-agent status icons; handle empty state gracefully [spec: ui] [size: S]
- [x] Write trace component (`ui/components/trace.py`): `render_trace_panel()` grouping `last_trace` by agent_id, rendering tool name, mode icon, status icon, duration per tool, error detail on failure [spec: ui] [size: M]
- [x] Write orchestration thread runner (`ui/runner.py`): `run_orchestration_sync(query, history, queue, app_context)` creating new event loop, running graph async, translating status events from LangGraph state to queue events, handling exceptions [spec: ui] [size: M]
- [x] Write main Streamlit app (`ui/app.py`): page config, sidebar layout, main chat area, `handle_user_input()` with thread spawn + queue polling loop, streaming chunk accumulation, `st.rerun()` orchestration [spec: ui] [size: L]

---

## Phase 6: Integration & Testing

- [x] Write config loader unit tests (`tests/unit/test_config_loader.py`): valid config parses correctly; missing required fields raise ConfigError; unknown provider raises; circular dependency detected; invalid handler path raises [spec: config] [size: M]
- [x] Write dependency resolver unit tests (`tests/unit/test_dependency_resolver.py`): simple rename → no LLM called; direct pass-through → no LLM called; type mismatch → LLM called; missing source field → LLM called; verify `used_llm` flag accuracy [spec: tool-execution] [size: M]
- [x] Write tool executor unit tests (`tests/unit/test_tool_executor.py`): single tool executes; two independent tools run in parallel (timing check); A→B chain: B gets A's output; failed tool doesn't block independent tools; downstream of failed tool also fails [spec: tool-execution] [size: M]
- [x] Write end-to-end integration test (`tests/integration/test_end_to_end.py`): Scenario B from demo spec (weather + news parallel query) using mock LLM adapters; verify routing plan has 2 tasks; verify both agents produce results; verify final_response is non-empty [spec: demo, parallel-dispatch] [size: L]
- [x] Manual smoke test all 4 demo scenarios (A, B, C, D from demo spec) with real LLM providers via Streamlit UI; verify tool trace renders correctly; verify streaming works [spec: demo, ui] [size: M]

---

## Phase 7: Hardening

- [x] Add LLM call log cost summary: print formatted per-turn cost table to stdout after each turn (model, tokens, estimated cost per LLMCallRecord); use publicly documented per-token pricing as constants [spec: config] [size: S]
- [x] Add startup validation sequence: on `streamlit run ui/app.py`, run config load → tool registry init → LLM adapter init → env var checks in order, print clear success or error summary before Streamlit serves [spec: config] [size: S]
- [x] Write `.env.example` with all required env vars, comments explaining each, and instructions for obtaining API keys [spec: config] [size: S]
- [x] Write `README.md`: installation, configuration, running the demo, adding a new agent walkthrough [spec: config] [size: M]

---

## Task Summary

| Phase | Tasks | S | M | L |
|-------|-------|---|---|---|
| 0: Foundation | 5 | 2 | 3 | 0 |
| 1: LLM Adapters | 5 | 2 | 3 | 0 |
| 2: Tool Infrastructure | 3 | 0 | 2 | 1 |
| 3: Graph | 5 | 0 | 3 | 2 |
| 4: Demo Tools | 3 | 3 | 0 | 0 |
| 5: UI | 6 | 2 | 2 | 2 (app.py) |
| 6: Testing | 5 | 0 | 3 | 2 |
| 7: Hardening | 4 | 3 | 1 | 0 |
| **Total** | **36** | **12** | **17** | **7** |
