"""Integration test — Scenario B: weather + news parallel query with mock LLMs."""

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.loader import load_config
from config.models import AppConfig
from core.context import AppContext
from core.graph import build_graph
from core.state import OrchestrationState
from llm.base import LLMAdapter, LLMCallRecord, LLMResponse, ToolSchema
from tools.registry import ToolRegistry


# ─── Mock LLM adapter ────────────────────────────────────────────────────────

class MockLLMAdapter:
    """Controllable mock adapter for integration tests."""

    def __init__(self, responses: Dict[str, str]):
        """Args: responses maps role → JSON string response."""
        self.responses = responses
        self.call_count = 0

    async def complete(
        self,
        messages: List[Dict[str, str]],
        tools=None,
        structured_output_schema=None,
    ) -> LLMResponse:
        self.call_count += 1
        # Determine which response to return based on content
        content = self.responses.get("default", '{"tasks": [], "execution_mode": "parallel", "routing_rationale": "mock"}')
        return LLMResponse(
            content=content,
            tool_calls=None,
            input_tokens=100,
            output_tokens=50,
            model="mock-model",
        )

    async def stream(self, messages: List[Dict[str, str]]) -> AsyncIterator[str]:
        yield "This is a unified response covering weather and news."


# ─── Test helpers ─────────────────────────────────────────────────────────────

def _load_real_config() -> AppConfig:
    """Load the real config (agents.yaml must be valid and demo tools importable)."""
    config_dir = Path(__file__).parent.parent.parent / "config"
    return load_config(
        settings_path=config_dir / "settings.yaml",
        agents_path=config_dir / "agents.yaml",
    )


def _build_mock_context(app_config: AppConfig, router_response: str, tool_plan_response: str) -> AppContext:
    """Build AppContext with mock LLM adapters."""
    router_llm = MockLLMAdapter({"default": router_response})
    tool_selector_llm = MockLLMAdapter({"default": tool_plan_response})
    transformer_llm = MockLLMAdapter({"default": "{}"})
    aggregator_llm = MockLLMAdapter({"default": "Great weather and news!"})

    registry = ToolRegistry()
    registry.load(app_config)

    return AppContext(
        router_llm=router_llm,
        tool_selector_llm=tool_selector_llm,
        transformer_llm=transformer_llm,
        aggregator_llm=aggregator_llm,
        tool_registry=registry,
        agent_configs={a.id: a for a in app_config.agents},
        app_config=app_config,
    )


# ─── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scenario_b_weather_and_news_parallel():
    """Scenario B: query routing to weather_agent + news_agent in parallel.

    Verifies:
    - Routing plan has 2 tasks
    - Both agents produce AgentResults
    - final_response is non-empty
    """
    app_config = _load_real_config()

    # Router returns 2 agents
    router_response = json.dumps({
        "tasks": [
            {"agent_id": "weather_agent", "sub_query": "What's the weather in Dhaka?"},
            {"agent_id": "news_agent", "sub_query": "Latest news about Bangladesh cricket"},
        ],
        "execution_mode": "parallel",
        "routing_rationale": "Query spans weather and news domains",
    })

    # Tool selector: for weather agent — select both weather tools
    weather_tool_plan = json.dumps({
        "tools": [
            {
                "tool_id": "get_current_weather",
                "initial_params": {"location": "Dhaka"},
                "depends_on": [],
            },
            {
                "tool_id": "get_weather_forecast",
                "initial_params": {"days": 3},
                "depends_on": ["get_current_weather"],
            },
        ]
    })
    # For news agent — search + summarize
    news_tool_plan = json.dumps({
        "tools": [
            {
                "tool_id": "search_news",
                "initial_params": {"query": "Bangladesh cricket", "max_results": 5},
                "depends_on": [],
            },
            {
                "tool_id": "summarize_articles",
                "initial_params": {},
                "depends_on": ["search_news"],
            },
        ]
    })

    # Build a context where tool selector alternates responses based on call count
    app_context = _build_mock_context(app_config, router_response, weather_tool_plan)
    # Override tool_selector to return different plans per agent call
    call_idx = [0]
    plans = [weather_tool_plan, news_tool_plan]

    async def mock_complete_selector(messages, tools=None, structured_output_schema=None):
        plan = plans[call_idx[0] % len(plans)]
        call_idx[0] += 1
        return LLMResponse(content=plan, tool_calls=None, input_tokens=50, output_tokens=30, model="mock")

    app_context.tool_selector_llm.complete = mock_complete_selector

    # Aggregator returns agent response
    async def mock_agg_complete(messages, tools=None, structured_output_schema=None):
        return LLMResponse(
            content="Great weather and news summary!", tool_calls=None,
            input_tokens=200, output_tokens=50, model="mock"
        )
    app_context.aggregator_llm.complete = mock_agg_complete

    graph = build_graph()
    initial_state: OrchestrationState = {
        "conversation_history": [],
        "current_query": "What's the weather in Dhaka and latest Bangladesh cricket news?",
        "current_agent_task": None,
        "routing_plan": None,
        "agent_results": {},
        "final_response": "",
        "execution_trace": [],
        "llm_call_log": [],
    }

    result = await graph.ainvoke(
        initial_state,
        config={"configurable": {"app_context": app_context, "status_queue": None}},
    )

    # Verify routing plan had 2 tasks
    assert result["routing_plan"] is not None
    assert len(result["routing_plan"]["tasks"]) == 2

    # Both agents produced results
    agent_results = result["agent_results"]
    assert "weather_agent" in agent_results
    assert "news_agent" in agent_results

    # Final response is non-empty
    assert result["final_response"], "final_response should not be empty"
    assert len(result["final_response"]) > 0


@pytest.mark.asyncio
async def test_scenario_a_single_agent_no_cross_aggregation():
    """Scenario A: single agent query — no cross-aggregation LLM call."""
    app_config = _load_real_config()

    router_response = json.dumps({
        "tasks": [
            {"agent_id": "weather_agent", "sub_query": "What's the weather in Dhaka?"},
        ],
        "execution_mode": "parallel",
        "routing_rationale": "Single domain: weather",
    })

    weather_tool_plan = json.dumps({
        "tools": [
            {"tool_id": "get_current_weather", "initial_params": {"location": "Dhaka"}, "depends_on": []},
        ]
    })

    app_context = _build_mock_context(app_config, router_response, weather_tool_plan)

    aggregator_call_count = [0]
    orig_stream = app_context.aggregator_llm.stream

    async def counting_stream(messages):
        aggregator_call_count[0] += 1
        yield "Weather response"

    app_context.aggregator_llm.stream = counting_stream

    # Also mock complete for intra-aggregation
    async def mock_agg_complete(messages, **kwargs):
        return LLMResponse(content="Nice weather in Dhaka!", tool_calls=None,
                           input_tokens=50, output_tokens=20, model="mock")
    app_context.aggregator_llm.complete = mock_agg_complete

    graph = build_graph()
    initial_state: OrchestrationState = {
        "conversation_history": [],
        "current_query": "What's the weather in Dhaka?",
        "current_agent_task": None,
        "routing_plan": None,
        "agent_results": {},
        "final_response": "",
        "execution_trace": [],
        "llm_call_log": [],
    }

    result = await graph.ainvoke(
        initial_state,
        config={"configurable": {"app_context": app_context, "status_queue": None}},
    )

    assert result["final_response"]
    # Cross-aggregation stream should NOT be called for single agent
    assert aggregator_call_count[0] == 0, (
        "Cross-aggregation LLM stream should not be called for single agent"
    )


@pytest.mark.asyncio
async def test_partial_failure_still_returns_response():
    """NFR-5: one agent fails, the other's response still reaches the user."""
    app_config = _load_real_config()

    router_response = json.dumps({
        "tasks": [
            {"agent_id": "weather_agent", "sub_query": "Weather in Dhaka"},
            {"agent_id": "news_agent", "sub_query": "Bangladesh cricket news"},
        ],
        "execution_mode": "parallel",
        "routing_rationale": "Two agents",
    })

    # Weather: trigger failure via FAIL location
    weather_tool_plan = json.dumps({
        "tools": [{"tool_id": "get_current_weather", "initial_params": {"location": "FAIL"}, "depends_on": []}]
    })
    news_tool_plan = json.dumps({
        "tools": [{"tool_id": "search_news", "initial_params": {"query": "cricket", "max_results": 3}, "depends_on": []}]
    })

    app_context = _build_mock_context(app_config, router_response, weather_tool_plan)
    call_idx = [0]
    plans = [weather_tool_plan, news_tool_plan]

    async def mock_complete_selector(messages, **kwargs):
        plan = plans[call_idx[0] % len(plans)]
        call_idx[0] += 1
        return LLMResponse(content=plan, tool_calls=None, input_tokens=50, output_tokens=30, model="mock")

    app_context.tool_selector_llm.complete = mock_complete_selector

    async def mock_agg_complete(messages, **kwargs):
        return LLMResponse(content="Partial info available", tool_calls=None,
                           input_tokens=50, output_tokens=20, model="mock")
    app_context.aggregator_llm.complete = mock_agg_complete

    async def mock_agg_stream(messages):
        yield "Partial response despite weather failure"
    app_context.aggregator_llm.stream = mock_agg_stream

    graph = build_graph()
    initial_state: OrchestrationState = {
        "conversation_history": [],
        "current_query": "Weather in Dhaka and cricket news",
        "current_agent_task": None,
        "routing_plan": None,
        "agent_results": {},
        "final_response": "",
        "execution_trace": [],
        "llm_call_log": [],
    }

    result = await graph.ainvoke(
        initial_state,
        config={"configurable": {"app_context": app_context, "status_queue": None}},
    )

    # System should not crash; final_response should exist
    assert result["final_response"], "System should return a response even with partial failure"
    assert "weather_agent" in result["agent_results"]
    assert "news_agent" in result["agent_results"]
