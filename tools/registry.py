"""Dynamic tool registry — loads tool handlers from config at startup."""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from config.models import AppConfig, ToolConfig
from llm.base import ToolSchema

logger = logging.getLogger(__name__)


@dataclass
class LoadedTool:
    """A tool with its config and its loaded handler function."""
    config: ToolConfig
    handler: Callable[..., Any]


class ToolRegistry:
    """Holds all loaded tool handlers, keyed by agent_id → tool_id."""

    def __init__(self) -> None:
        # registry[agent_id][tool_id] = LoadedTool
        self._registry: Dict[str, Dict[str, LoadedTool]] = {}

    def load(self, app_config: AppConfig) -> None:
        """Load all tool handlers from the application config.

        Uses importlib to dynamically import handler functions from their
        dotted module paths. Config validation has already verified these
        paths are importable.

        Args:
            app_config: Validated AppConfig with all agent/tool definitions.
        """
        for agent in app_config.agents:
            self._registry[agent.id] = {}
            for tool in agent.tools:
                module_path, func_name = tool.handler.rsplit(".", 1)
                module = importlib.import_module(module_path)
                handler_fn = getattr(module, func_name)
                self._registry[agent.id][tool.id] = LoadedTool(
                    config=tool,
                    handler=handler_fn,
                )
                logger.debug(
                    "Loaded tool: agent=%s tool=%s handler=%s",
                    agent.id,
                    tool.id,
                    tool.handler,
                )

    def get_tool(self, agent_id: str, tool_id: str) -> LoadedTool:
        """Retrieve a loaded tool by agent and tool ID.

        Raises:
            KeyError: If agent_id or tool_id not found.
        """
        return self._registry[agent_id][tool_id]

    def get_agent_tools(self, agent_id: str) -> Dict[str, LoadedTool]:
        """Return all loaded tools for an agent."""
        return self._registry.get(agent_id, {})

    def get_tool_schemas(self, agent_id: str) -> List[ToolSchema]:
        """Return ToolSchema list for the LLM tool selector prompt.

        Appends dependency info to each tool's description so the LLM
        understands which tools depend on others.

        Args:
            agent_id: The agent whose tools to describe.

        Returns:
            List of ToolSchema ready for LLMAdapter.complete(tools=...).
        """
        schemas: List[ToolSchema] = []
        for tool_id, loaded in self._registry.get(agent_id, {}).items():
            description = loaded.config.description
            if loaded.config.depends_on:
                dep_ids = [d.tool_id for d in loaded.config.depends_on]
                description += f" (depends on: {', '.join(dep_ids)})"
            schemas.append(
                ToolSchema(
                    name=tool_id,
                    description=description,
                    input_schema=loaded.config.input_schema,
                )
            )
        return schemas

    def agent_ids(self) -> List[str]:
        """Return list of all registered agent IDs."""
        return list(self._registry.keys())
