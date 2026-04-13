# Issues: multi-agent-orchestration

---

## ISSUE-001: Agent-level parallel timing not covered by automated test
- **Severity**: Minor
- **Requirement**: NFR-1
- **Tag**: [requirement-gap]
- **Steps to Reproduce**: Review `tests/integration/test_end_to_end.py` — `test_scenario_b_weather_and_news_parallel` asserts both agents produce results but does not assert wall-clock timing.
- **Expected**: Automated test verifies total dispatch time ≤ max(agent_times) × 1.1 + 2s.
- **Actual**: No such timing assertion exists.
- **Suggested Fix**: Add a test with mock agents that sleep 0.3s each; assert `elapsed < 0.6s`. LangGraph's `Send` API guarantees concurrency, so this is a regression guard.

---

## ISSUE-002: Streaming LLM token count is estimated, not exact
**Status: RESOLVED**

- **Severity**: Major
- **Requirement**: NFR-4
- **Tag**: [design-issue]
- **Steps to Reproduce**:
  1. Submit a multi-agent query (e.g., "Weather in Dhaka and latest news").
  2. Observe the TURN COST SUMMARY printed to stdout.
  3. The `aggregator` row uses `est_in = len(text) // 4` and `est_out = len(response) // 4`.
- **Expected**: Exact token counts from the provider's streaming API.
- **Actual**: Character-count estimate (off by ±30-50%).
- **Location**: `core/aggregator.py:128-131`
- **Suggested Fix**:
  - Anthropic: capture `usage` from `message_stop` event in `AnthropicAdapter.stream()`.
  - OpenAI: add `stream_options={"include_usage": True}` and capture final `usage` chunk.
  - Gemini: read `usage_metadata` from final response chunk.
  - Change `stream()` signature to optionally return usage alongside chunks, or add a `stream_with_usage()` variant.

---

## ISSUE-003: Tool execution trace missing input parameters (DR-3)
- **Severity**: Minor
- **Requirement**: DR-3
- **Tag**: [requirement-gap]
- **Steps to Reproduce**: Submit any query with tools. Inspect `result["execution_trace"]` — no `input_params` field.
- **Expected**: `ToolExecutionResult.to_dict()` includes `input_params: dict` with resolved parameters.
- **Actual**: Field absent.
- **Location**: `tools/executor.py:50-61` (`ToolExecutionResult.to_dict()`), `tools/executor.py:265-290` (`_execute_single_tool`)
- **Suggested Fix**:
  1. Add `input_params: Dict[str, Any]` field to `ToolExecutionResult`.
  2. Populate it in `_execute_single_tool` after dependency resolution (before calling the handler).
  3. Sanitize: skip any key whose name contains `key`, `secret`, `token`, `password`.

---

## ISSUE-004: settings.yaml defaults to Anthropic — breaks Gemini-only users in non-UI paths
**Status: RESOLVED**

- **Severity**: Major
- **Requirement**: FR-6.3
- **Tag**: [design-issue]
- **Steps to Reproduce**:
  1. Have only `GOOGLE_API_KEY` in `.env`.
  2. Run `build_app_context(load_config())` directly (outside Streamlit UI).
  3. `llm/factory.py:get_adapter()` raises `ConfigError: Missing environment variable: ANTHROPIC_API_KEY`.
- **Expected**: Default config works for the user's available provider.
- **Actual**: Defaults hardcoded to Anthropic in both `config/settings.yaml` and `config/loader.py:_DEFAULT_LLM_ROLES`.
- **Location**:
  - `config/settings.yaml:1-17`
  - `config/loader.py:19-24` (`_DEFAULT_LLM_ROLES`)
- **Suggested Fix**:
  1. Update `config/settings.yaml` to use `gemini` / `gemini-2.0-flash` / `gemini-2.0-flash-lite`.
  2. Update `_DEFAULT_LLM_ROLES` in `config/loader.py` to match.
  3. Long-term: auto-detect available provider in `load_config()` if no `settings.yaml` is present.

---

## ISSUE-005: DR-1 requirement divergence — history now persisted to disk
- **Severity**: Minor
- **Requirement**: DR-1
- **Tag**: [requirement-gap]
- **Steps to Reproduce**: Submit any query. Observe `.chat_history.json` created at project root. Refresh the browser tab — chat history reloads.
- **Expected per DR-1**: "Retention: duration of the Streamlit session only (no persistence to disk or DB)."
- **Actual**: History is saved to `.chat_history.json` and survives page refreshes and server restarts. Max 200 messages. Users can clear via the "Clear chat history" button.
- **Root Cause**: User explicitly requested cross-refresh persistence; `ui/persistence.py` was added to satisfy this request. The deviation improves UX for a local single-user tool and introduces no security risk.
- **Suggested Fix**: PM to update DR-1 text: "Session history is maintained in memory and optionally persisted to a local file (`.chat_history.json`) so it survives page refreshes. Max 200 messages. No database. Users can clear via the sidebar button."

---

## ISSUE-006: Cost table missing Gemini 3.x model pricing
- **Severity**: Minor
- **Requirement**: NFR-4
- **Tag**: [requirement-gap]
- **Steps to Reproduce**:
  1. Select `gemini-3.1-pro-preview` (or any gemini-3.x model) from the UI model selector.
  2. Submit any query.
  3. Observe TURN COST SUMMARY in stdout — all rows show `~$0.0000`.
- **Expected**: Cost displayed using model's per-token pricing.
- **Actual**: Models `gemini-3.1-pro-preview`, `gemini-3-flash-preview`, `gemini-3.1-flash-lite-preview` are absent from `_COST_PER_1M` dict in `core/aggregator.py:21-37`. The `dict.get(model, {"in": 0.0, "out": 0.0})` fallback silently returns zero.
- **Location**: `core/aggregator.py:21-37`
- **Suggested Fix**: Add entries for all models listed in `ui/model_config.py`. Use Google's official pricing page or best-available estimate. Example:
  ```python
  "gemini-3.1-pro-preview": {"in": 1.25, "out": 10.0},
  "gemini-3-flash-preview": {"in": 0.15, "out": 0.6},
  "gemini-3.1-flash-lite-preview": {"in": 0.075, "out": 0.3},
  ```
