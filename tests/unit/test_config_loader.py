"""Unit tests for config/loader.py."""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.loader import ConfigError, load_config
from config.models import AppConfig


def _write_files(tmp_path: Path, settings: str, agents: str):
    s = tmp_path / "settings.yaml"
    a = tmp_path / "agents.yaml"
    s.write_text(settings)
    a.write_text(agents)
    return s, a


_VALID_SETTINGS = """\
llm_roles:
  router:
    provider: anthropic
    model: claude-opus-4-6
    temperature: 0.0
  tool_selector:
    provider: openai
    model: gpt-4o
    temperature: 0.0
  transformer:
    provider: openai
    model: gpt-4o-mini
    temperature: 0.0
  aggregator:
    provider: openai
    model: gpt-4o-mini
    temperature: 0.3
"""

_VALID_AGENTS = """\
agents:
  - id: weather_agent
    name: Weather Agent
    description: Handles weather queries
    tools:
      - id: get_current_weather
        name: Get Current Weather
        description: Returns weather
        handler: demo.tools.weather.get_current_weather
        input_schema:
          type: object
          properties:
            location: {type: string}
          required: [location]
        output_schema:
          type: object
          properties:
            location: {type: string}
"""


def test_valid_config_parses(tmp_path):
    s, a = _write_files(tmp_path, _VALID_SETTINGS, _VALID_AGENTS)
    config = load_config(settings_path=s, agents_path=a)
    assert isinstance(config, AppConfig)
    assert len(config.agents) == 1
    assert config.agents[0].id == "weather_agent"
    assert config.llm_roles.router.provider == "anthropic"


def test_missing_agents_yaml_raises(tmp_path):
    s = tmp_path / "settings.yaml"
    s.write_text(_VALID_SETTINGS)
    missing = tmp_path / "nonexistent.yaml"
    with pytest.raises(ConfigError, match="not found"):
        load_config(settings_path=s, agents_path=missing)


def test_missing_settings_yaml_uses_defaults(tmp_path):
    a = tmp_path / "agents.yaml"
    a.write_text(_VALID_AGENTS)
    missing_settings = tmp_path / "no_settings.yaml"
    config = load_config(settings_path=missing_settings, agents_path=a)
    # Should use defaults (Gemini, so no provider key is required)
    assert config.llm_roles.router.provider == "gemini"
    assert config.llm_roles.router.model == "gemini-2.0-flash"


def test_unknown_provider_raises(tmp_path):
    bad_settings = _VALID_SETTINGS.replace("anthropic", "unknown_provider")
    s, a = _write_files(tmp_path, bad_settings, _VALID_AGENTS)
    with pytest.raises(ConfigError):
        load_config(settings_path=s, agents_path=a)


def test_duplicate_agent_id_raises(tmp_path):
    agents_yaml = """\
agents:
  - id: weather_agent
    name: Weather Agent
    description: First
    tools:
      - id: tool_a
        name: Tool A
        description: A tool
        handler: demo.tools.weather.get_current_weather
        input_schema: {type: object, properties: {location: {type: string}}, required: [location]}
        output_schema: {type: object, properties: {location: {type: string}}}
  - id: weather_agent
    name: Weather Agent Duplicate
    description: Second
    tools:
      - id: tool_b
        name: Tool B
        description: B tool
        handler: demo.tools.weather.get_current_weather
        input_schema: {type: object, properties: {location: {type: string}}, required: [location]}
        output_schema: {type: object, properties: {location: {type: string}}}
"""
    s, a = _write_files(tmp_path, _VALID_SETTINGS, agents_yaml)
    with pytest.raises(ConfigError, match="Duplicate agent id"):
        load_config(settings_path=s, agents_path=a)


def test_invalid_handler_path_raises(tmp_path):
    agents_yaml = """\
agents:
  - id: bad_agent
    name: Bad Agent
    description: Test
    tools:
      - id: bad_tool
        name: Bad Tool
        description: This tool has a bad handler
        handler: nonexistent.module.some_function
        input_schema: {type: object, properties: {x: {type: string}}, required: [x]}
        output_schema: {type: object, properties: {y: {type: string}}}
"""
    s, a = _write_files(tmp_path, _VALID_SETTINGS, agents_yaml)
    with pytest.raises(ConfigError, match="cannot import module"):
        load_config(settings_path=s, agents_path=a)


def test_circular_dependency_raises(tmp_path):
    agents_yaml = """\
agents:
  - id: test_agent
    name: Test Agent
    description: Tests circular deps
    tools:
      - id: tool_a
        name: Tool A
        description: A
        handler: demo.tools.weather.get_current_weather
        input_schema: {type: object, properties: {location: {type: string}}, required: [location]}
        output_schema: {type: object, properties: {location: {type: string}}}
        depends_on:
          - tool_id: tool_b
            mappings:
              - source_field: location
                target_field: location
      - id: tool_b
        name: Tool B
        description: B
        handler: demo.tools.weather.get_weather_forecast
        input_schema: {type: object, properties: {location: {type: string}}, required: [location]}
        output_schema: {type: object, properties: {location: {type: string}}}
        depends_on:
          - tool_id: tool_a
            mappings:
              - source_field: location
                target_field: location
"""
    s, a = _write_files(tmp_path, _VALID_SETTINGS, agents_yaml)
    with pytest.raises(ConfigError, match="circular"):
        load_config(settings_path=s, agents_path=a)


def test_nonexistent_dependency_tool_raises(tmp_path):
    agents_yaml = """\
agents:
  - id: test_agent
    name: Test Agent
    description: Test
    tools:
      - id: tool_a
        name: Tool A
        description: Depends on nonexistent
        handler: demo.tools.weather.get_current_weather
        input_schema: {type: object, properties: {location: {type: string}}, required: [location]}
        output_schema: {type: object, properties: {location: {type: string}}}
        depends_on:
          - tool_id: nonexistent_tool
            mappings:
              - source_field: x
                target_field: y
"""
    s, a = _write_files(tmp_path, _VALID_SETTINGS, agents_yaml)
    with pytest.raises(ConfigError, match="referenced tool_id not found"):
        load_config(settings_path=s, agents_path=a)


def test_temperature_out_of_range_raises(tmp_path):
    bad_settings = _VALID_SETTINGS.replace("temperature: 0.0\n  tool_selector:", "temperature: 1.5\n  tool_selector:")
    s, a = _write_files(tmp_path, bad_settings, _VALID_AGENTS)
    with pytest.raises(ConfigError):
        load_config(settings_path=s, agents_path=a)
