"""Config loading, validation, and startup fail-fast checks."""

import importlib
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import ValidationError

from config.models import AppConfig, LLMRolesConfig, LLMRoleConfig

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).parent
_SETTINGS_PATH = _CONFIG_DIR / "settings.yaml"
_AGENTS_PATH = _CONFIG_DIR / "agents.yaml"

_DEFAULT_LLM_ROLES: Dict[str, Any] = {
    "router": {"provider": "gemini", "model": "gemini-2.0-flash", "temperature": 0.0},
    "tool_selector": {"provider": "gemini", "model": "gemini-2.0-flash", "temperature": 0.0},
    "transformer": {"provider": "gemini", "model": "gemini-2.0-flash-lite", "temperature": 0.0},
    "aggregator": {"provider": "gemini", "model": "gemini-2.0-flash-lite", "temperature": 0.3},
}


class ConfigError(Exception):
    """Raised for config validation failures with descriptive messages."""


def load_config(
    settings_path: Optional[Path] = None,
    agents_path: Optional[Path] = None,
) -> AppConfig:
    """Load, merge, and validate application configuration.

    Args:
        settings_path: Override path to settings.yaml (for testing).
        agents_path: Override path to agents.yaml (for testing).

    Returns:
        Validated AppConfig.

    Raises:
        ConfigError: Any validation failure with a descriptive message.
    """
    settings_path = settings_path or _SETTINGS_PATH
    agents_path = agents_path or _AGENTS_PATH

    # Step 1: Load settings.yaml (optional — use defaults if absent)
    settings_data: Dict[str, Any] = {}
    if settings_path.exists():
        try:
            raw = settings_path.read_text()
            loaded = yaml.safe_load(raw)
            if loaded is not None:
                settings_data = loaded
        except yaml.YAMLError as e:
            raise ConfigError(f"[settings.yaml] YAML parse error: {e}") from e
    else:
        logger.info("settings.yaml not found — using defaults.")

    # Step 2: Load agents.yaml (required)
    if not agents_path.exists():
        raise ConfigError(
            f"[agents.yaml] File not found at {agents_path}. "
            "Create agents.yaml to define your sub-agents."
        )
    try:
        raw = agents_path.read_text()
        agents_data = yaml.safe_load(raw)
        if agents_data is None:
            raise ConfigError("[agents.yaml] File is empty.")
    except yaml.YAMLError as e:
        raise ConfigError(f"[agents.yaml] YAML parse error: {e}") from e

    # Step 3: Build merged config dict and validate with Pydantic
    llm_roles_raw = settings_data.get("llm_roles", _DEFAULT_LLM_ROLES)
    merged: Dict[str, Any] = {
        "llm_roles": llm_roles_raw,
        "agents": agents_data.get("agents", []),
    }

    try:
        config = AppConfig.model_validate(merged)
    except ValidationError as e:
        # Produce a readable summary of all validation errors
        msgs = []
        for err in e.errors():
            loc = " → ".join(str(x) for x in err["loc"])
            msgs.append(f"  [{loc}] {err['msg']}")
        raise ConfigError("Config validation failed:\n" + "\n".join(msgs)) from e

    # Step 4: Validate agent id uniqueness
    agent_ids = [a.id for a in config.agents]
    seen: set = set()
    for aid in agent_ids:
        if aid in seen:
            raise ConfigError(
                f"[agents.yaml] Duplicate agent id: '{aid}'. "
                "Each agent must have a unique id."
            )
        seen.add(aid)

    # Step 5: Validate tool id uniqueness within each agent
    for agent in config.agents:
        tool_ids = [t.id for t in agent.tools]
        seen_tools: set = set()
        for tid in tool_ids:
            if tid in seen_tools:
                raise ConfigError(
                    f"[agents.yaml] agent '{agent.id}' has duplicate tool id: '{tid}'."
                )
            seen_tools.add(tid)

    # Step 6: Validate handler importability
    for agent in config.agents:
        for tool in agent.tools:
            _validate_handler(agent.id, tool.id, tool.handler)

    # Step 7: Validate dependency references and detect cycles
    for agent in config.agents:
        tool_id_set = {t.id for t in agent.tools}
        for tool in agent.tools:
            for dep in tool.depends_on:
                if dep.tool_id not in tool_id_set:
                    raise ConfigError(
                        f"[agents.yaml] agent '{agent.id}' → tool '{tool.id}' → "
                        f"depends_on '{dep.tool_id}': referenced tool_id not found "
                        "in agent's tool list."
                    )
        _detect_cycles(agent.id, agent.tools)

    return config


def _validate_handler(agent_id: str, tool_id: str, handler: str) -> None:
    """Validate that a tool handler dotted path is importable."""
    if "." not in handler:
        raise ConfigError(
            f"[agents.yaml] agent '{agent_id}' → tool '{tool_id}' → handler "
            f"'{handler}': must be a dotted module path (e.g., 'demo.tools.weather.get_current_weather')."
        )
    module_path, func_name = handler.rsplit(".", 1)
    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        raise ConfigError(
            f"[agents.yaml] agent '{agent_id}' → tool '{tool_id}' → handler "
            f"'{handler}': cannot import module '{module_path}'. Error: {e}"
        ) from e
    if not hasattr(module, func_name):
        raise ConfigError(
            f"[agents.yaml] agent '{agent_id}' → tool '{tool_id}' → handler "
            f"'{handler}': function '{func_name}' not found in module '{module_path}'."
        )


def _detect_cycles(agent_id: str, tools) -> None:
    """Detect circular dependencies in an agent's tool list using DFS."""
    # Build adjacency list: tool_id → list of tool_ids it depends on
    graph: Dict[str, list] = {t.id: [d.tool_id for d in t.depends_on] for t in tools}

    visited: set = set()
    rec_stack: set = set()

    def dfs(node: str) -> None:
        visited.add(node)
        rec_stack.add(node)
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                dfs(neighbor)
            elif neighbor in rec_stack:
                raise ConfigError(
                    f"[agents.yaml] agent '{agent_id}': circular tool dependency "
                    f"detected involving tool '{neighbor}'."
                )
        rec_stack.discard(node)

    for tool_id in graph:
        if tool_id not in visited:
            dfs(tool_id)
