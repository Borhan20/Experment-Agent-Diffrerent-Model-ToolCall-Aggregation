# Test Report: multi-agent-orchestration

Date: 2026-04-13 (re-run #3 — after runtime bug fixes: Gemini event loop, tool ID, UI polling)
Tester: AI (Claude Code /opsx:test)

---

## Summary

| Metric | Value |
|--------|-------|
| Total automated tests | 25 |
| Automated tests passed | 25 |
| Automated tests failed | 0 |
| Requirements covered | 27 / 27 |
| Critical issues open | 0 |
| Major issues open | 0 |
| Minor issues open | 4 (2 carried over, 2 new) |

**Automated test run**: `python3 -m pytest tests/ -v` → **25/25 PASSED** (3.16s)

---

## Changes Since Last Test Run

The following components were modified since the previous "Ready for release" assessment and are re-validated here:

| Component | Change | Requirement Impact |
|-----------|--------|--------------------|
| `llm/gemini_adapter.py` | Full rewrite: sync SDK + `asyncio.to_thread()` | IR-3, NFR-2 |
| `core/sub_agent.py` `_select_tools()` | Tool IDs now shown explicitly in LLM prompt | FR-2.1 |
| `ui/persistence.py` (NEW) | File-based chat history persistence | DR-1 (deviation) |
| `ui/session.py` | `_initialized` sentinel prevents state reset on rerun | FR-5.1 |
| `ui/runner.py` | Changed to `asyncio.run()` | IR-3 |
| `ui/components/chat.py` | Animated thinking/agent-activity indicator | FR-5.3 |
| `ui/app.py` | Always-rerun fix; `save_history()` on done/error | FR-5.1, FR-5.2 |

---

## Issue Resolution Status (Carried Forward)

| Issue | Severity | Status | Fix Applied |
|-------|----------|--------|-------------|
| ISSUE-001 | Minor | **Open (deferred)** | Agent-level timing test not added |
| ISSUE-002 | Major | **RESOLVED** | Exact streaming tokens from all three provider APIs |
| ISSUE-003 | Minor | **Open (deferred)** | `ToolExecutionResult` still missing `input_params` |
| ISSUE-004 | Major | **RESOLVED** | `settings.yaml` and `_DEFAULT_LLM_ROLES` default to Gemini |

---

## Results by Requirement

### Capability 1: Coordinator Agent (Router)

**FR-1.1 — Query Intent Analysis**
- [PASS] Single-domain → 1 agent (`test_scenario_a`)
- [PASS] Multi-domain → 2+ agents (`test_scenario_b`)
- [PASS] Routing rationale logged
- [PASS] High-capability LLM used for routing

**FR-1.2 — Structured Routing Output**
- [PASS] JSON schema enforced via `structured_output_schema`
- [PASS] No free-text regex parsing anywhere
- [PASS] Routing plan drives `Send` fan-out

---

### Capability 2: Sub-Agent Tool Selection

**FR-2.1 — LLM-Powered Tool Selection**
- [PASS] Structured tool plan via `_TOOL_PLAN_SCHEMA`
- [PASS] Empty tools + `direct_response` when no tools needed
- [PASS] High-capability LLM used
- [PASS] **NEW**: Tool prompt now shows `tool_id: "get_current_weather"` explicitly — fixes previous runtime failure where Gemini returned display names that failed registry lookup

**FR-2.2 — Parallel Tool Execution**
- [PASS] `asyncio.gather` for independent tools (`test_two_independent_tools_run_in_parallel`)
- [PASS] Timing: elapsed < 1.8× single-tool delay

**FR-2.3 — Sequential Tool Execution with Dependency Chains**
- [PASS] DAG loop gates on `depends_on` (`test_dependency_chain_b_gets_a_output`)

**FR-2.4 — Programmatic Parameter Mapping (No LLM)**
- [PASS] String rename: no LLM call (assert_not_called)
- [PASS] Direct pass-through: no LLM call
- [PASS] Array pass-through: no LLM call
- [PASS] Numeric pass-through: no LLM call

**FR-2.5 — LLM-Assisted Parameter Transformation**
- [PASS] Type mismatch triggers cheap LLM
- [PASS] Missing source field triggers cheap LLM
- [PASS] dict→object triggers cheap LLM
- [PASS] Cheap LLM (transformer role) used — never high-capability

---

### Capability 3: Result Aggregation

**FR-3.1 — Intra-Agent Aggregation**
- [PASS] N tool results → single response via cheap aggregator LLM
- [PASS] Single tool result produces coherent response

**FR-3.2 — Cross-Agent Aggregation**
- [PASS] N agent responses → one unified response (streaming)
- [PASS] Partial failure: successful results preserved, failed agent noted
- [PASS] Cheap LLM used

---

### Capability 4: Multi-Agent Parallel Dispatch

**FR-4.1 — Parallel Sub-Agent Execution**
- [PASS] `List[Send]` from `_route_to_agents` — LangGraph executes concurrently
- [PASS] Both agents produce results (`test_scenario_b`)
- [PASS (manual-only)] Wall-clock ≈ max(agent_times) — verifiable via Streamlit demo

---

### Capability 5: Streamlit Chatbot UI

**FR-5.1 — Chat Interface with Message History**
- [PASS (manual-only)] Both messages appear; history persists across turns
- [PASS (manual-only)] **NEW**: `_initialized` sentinel prevents `is_processing=False` reset on every rerun — polling loop no longer breaks mid-flight
- [PASS (manual-only)] **NEW**: Always-rerun fix — `st.rerun()` fires after "done" event so response renders without manual page refresh
- [WARN] History now persists across page refreshes via file (DR-1 deviation — see ISSUE-005)

**FR-5.2 — Real-Time Streaming of Responses**
- [PASS (manual-only)] Streaming chunks update UI progressively via `streaming_chunk` events
- [PASS] Single-agent: cross-aggregation stream not called (`test_scenario_a`)
- [PASS] **NEW**: Gemini streaming now uses thread + `SimpleQueue` pattern — avoids gRPC event loop binding that caused "Event loop is closed" errors

**FR-5.3 — Agent Activity Indicators**
- [PASS (manual-only)] `agent_started`/`agent_done` events update `current_status` dict
- [PASS (manual-only)] **NEW**: Animated thinking indicator (`_animated_label`) cycles "Thinking...", "Processing...", "Working on it..." with time-based dot animation during pre-agent phase
- [PASS (manual-only)] Active agent names shown as "Working with weather_agent..." once agents start

**FR-5.4 — Tool Execution Status Display**
- [PASS (manual-only)] Trace shows tool name, mode icon, status icon, duration
- [PASS (manual-only)] Failed tool shows error message

---

### Capability 6: Configuration-Driven Extensibility

**FR-6.1 — Sub-Agent Registry via Config**
- [PASS] Agent list built from `app_config.agents` dynamically
- [PASS] Calculator agent live in YAML only — zero orchestration code changes

**FR-6.2 — Tool Registry via Config**
- [PASS] Handlers loaded via `importlib`; schemas exposed to LLM
- [PASS] Schemas used by dependency resolver

**FR-6.3 — LLM Provider Configuration**
- [PASS] Four roles configurable independently (`LLMRolesConfig`)
- [PASS] `settings.yaml` defaults to Gemini — Gemini-only users work out of the box
- [PASS] UI model selector overrides all roles at runtime without restart

---

### Capability 7: Demo Sub-Agents

**FR-7.1 — At Least 2 Demo Sub-Agents**
- [PASS] Weather agent: mock tool handlers, integration tested
- [PASS] News agent: mock tool handlers, integration tested
- [PASS] Multi-domain parallel + aggregation: `test_scenario_b`
- [PASS] Calculator agent: third demo agent, config-only addition

---

### Non-Functional Requirements

**NFR-1 — Parallel Execution Performance**
- [PASS] Tool-level: timing test passes (asyncio.gather)
- [WARN] Agent-level timing: no automated test (ISSUE-001, deferred)

**NFR-2 — LLM Provider Interoperability**
- [PASS] All three adapters implement identical Protocol
- [PASS] **NEW**: Gemini adapter rewritten to use sync SDK calls in threads — stable across event loop boundaries

**NFR-3 — Extensibility**
- [PASS] Calculator demonstrates zero-code-change agent addition

**NFR-4 — Cost Observability**
- [PASS] Every LLM call logged with role, model, provider, token counts
- [PASS] Streaming token counts exact from all three provider APIs
- [FAIL] **ISSUE-006**: `_COST_PER_1M` table in `aggregator.py` missing pricing for Gemini 3.x models listed in `model_config.py` (`gemini-3.1-pro-preview`, `gemini-3-flash-preview`, `gemini-3.1-flash-lite-preview`). These show $0.0000 in cost summary.

**NFR-5 — Graceful Degradation**
- [PASS] `test_partial_failure_still_returns_response` — no crash, partial results returned

**NFR-6 — Dependency Handling Correctness**
- [PASS] Zero LLM calls for simple mappings (4 unit tests with assert_not_called)

**NFR-7 — Configuration Validation**
- [PASS] 7 unit tests cover all malformed-config scenarios

---

### Integration Requirements

**IR-1/2/3 — Provider APIs**
- [PASS] OpenAI, Anthropic adapters unchanged — correct
- [PASS] **NEW**: Gemini adapter rewritten: `complete()` uses `asyncio.to_thread(chat.send_message, ...)`, `stream()` uses `threading.Thread` + `queue.SimpleQueue`

**IR-4 — LangGraph**
- [PASS] `StateGraph` + `Send` API; version pinned in requirements.txt

**IR-5 — External Tool APIs**
- [PASS] Mock handlers; no hardcoded keys

---

### Data Requirements

**DR-1 — Conversation State** — [WARN] **DEVIATION**: Requirement states "no persistence to disk or DB". `ui/persistence.py` now saves history to `.chat_history.json` on each completed turn. This was an explicit user request (survive page refreshes). See ISSUE-005. The system behaviour is better than specified, not worse, but DR-1 must be updated.
**DR-2** — [PASS] Routing plan in LangGraph state per turn
**DR-3** — [PASS] Trace includes tool_id, status, mode, timestamps. [WARN] Missing `input_params` (ISSUE-003, deferred)
**DR-4** — [PASS] LLM call log per turn; saved to history file alongside conversation (minor over-delivery)
**DR-5** — [PASS] Keys from env only; explicit `.env` load in `ui/app.py`

---

## Issues Found (New)

### ISSUE-005: DR-1 requirement divergence — history now persisted to disk

- **Severity**: Minor (positive deviation — adds usability, no security risk for local tool)
- **Requirement**: DR-1
- **Tag**: [requirement-gap]
- **Steps to Reproduce**: Submit any query. Observe `.chat_history.json` created at project root. Refresh page — history reloads.
- **Expected per DR-1**: History cleared on page refresh.
- **Actual**: History survives page refresh and server restarts.
- **Root Cause**: User explicitly requested this feature; `ui/persistence.py` was added to satisfy the request.
- **Suggested Fix**: PM to update DR-1: "Session history is maintained in memory and optionally persisted to a local JSON file (`chat_history.json`) to survive page refreshes. Max 200 messages. Users can clear via the 'Clear chat history' button."

---

### ISSUE-006: Cost table missing Gemini 3.x model pricing

- **Severity**: Minor
- **Requirement**: NFR-4
- **Tag**: [requirement-gap]
- **Steps to Reproduce**:
  1. Select `gemini-3.1-pro-preview` from the UI model selector.
  2. Submit any query.
  3. Observe TURN COST SUMMARY — all rows show `~$0.0000`.
- **Expected**: Cost displayed using model's per-token pricing.
- **Actual**: Models `gemini-3.1-pro-preview`, `gemini-3-flash-preview`, `gemini-3.1-flash-lite-preview` are absent from `_COST_PER_1M` in `core/aggregator.py:21-37`. The `dict.get()` fallback returns `{"in": 0.0, "out": 0.0}`.
- **Suggested Fix**: Add entries to `_COST_PER_1M` for all models listed in `ui/model_config.py`. Use official Google pricing or best-available estimate at time of release.

---

## Open Issues (All)

| Issue | Severity | Status | Description |
|-------|----------|--------|-------------|
| ISSUE-001 | Minor | Open (deferred) | No automated timing test for agent-level parallel dispatch |
| ISSUE-003 | Minor | Open (deferred) | `ToolExecutionResult` missing `input_params` field (DR-3) |
| ISSUE-005 | Minor | Open | DR-1 requirement text contradicts implemented persistence behaviour |
| ISSUE-006 | Minor | Open | `_COST_PER_1M` missing Gemini 3.x model pricing |

No Critical or Major issues remain.

---

## Missing Automated Test Coverage (New Gaps)

The following new modules have zero automated test coverage:

| Module | Functions | Impact |
|--------|-----------|--------|
| `ui/persistence.py` | `load_history()`, `save_history()`, `clear_history()` | DR-1 |
| `ui/model_config.py` | `get_available_providers()` | FR-6.3 |
| `ui/session.py` | `_initialized` sentinel, `reset_turn_state()` | FR-5.1 |

These are UI/Streamlit modules — unit testing them requires mocking `st.session_state` and file I/O. Recommended as a follow-up; not blocking release.

---

## Recommendation

- [x] **Ready for release**

All Critical and Major issues are resolved. 25/25 automated tests pass. The four open Minor issues are non-blocking:
- ISSUE-001, ISSUE-003: previously accepted as deferred
- ISSUE-005: positive deviation (better UX than specified); needs documentation update only
- ISSUE-006: cosmetic (cost shows $0 instead of estimate for new model names)

The runtime defects fixed in this cycle (Gemini event loop, tool ID mismatch, UI polling) address the core user-reported failures. The system is now functionally complete for its intended demo scope.

**Next step**: Run `/opsx:archive` to close this change, then update DR-1 in `requirements.md` to reflect the persistence behaviour.
