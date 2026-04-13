"""Application context — holds initialized LLM adapters and registries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from config.models import AgentConfig, AppConfig
from llm.base import LLMAdapter
from tools.registry import ToolRegistry


@dataclass
class AppContext:
    """Initialized runtime context passed to LangGraph nodes via config."""
    router_llm: LLMAdapter
    tool_selector_llm: LLMAdapter
    transformer_llm: LLMAdapter
    aggregator_llm: LLMAdapter
    tool_registry: ToolRegistry
    agent_configs: Dict[str, AgentConfig]   # keyed by agent.id
    app_config: AppConfig


def build_app_context(app_config: AppConfig) -> AppContext:
    """Build AppContext from a validated AppConfig.

    Initializes all LLM adapters and the tool registry.
    Raises ConfigError if required API keys are missing.

    Args:
        app_config: Validated AppConfig from config.loader.load_config().

    Returns:
        Fully initialized AppContext ready for use.
    """
    from llm.factory import get_adapter

    router_llm = get_adapter(app_config.llm_roles.router)
    tool_selector_llm = get_adapter(app_config.llm_roles.tool_selector)
    transformer_llm = get_adapter(app_config.llm_roles.transformer)
    aggregator_llm = get_adapter(app_config.llm_roles.aggregator)

    registry = ToolRegistry()
    registry.load(app_config)

    agent_configs = {agent.id: agent for agent in app_config.agents}

    return AppContext(
        router_llm=router_llm,
        tool_selector_llm=tool_selector_llm,
        transformer_llm=transformer_llm,
        aggregator_llm=aggregator_llm,
        tool_registry=registry,
        agent_configs=agent_configs,
        app_config=app_config,
    )
