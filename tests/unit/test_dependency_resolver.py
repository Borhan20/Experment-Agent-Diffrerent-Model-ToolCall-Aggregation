"""Unit tests for core/dependency_resolver.py."""

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.models import ToolDependencyConfig, ToolMappingConfig
from core.dependency_resolver import resolve
from llm.base import LLMResponse


def _make_dep(source: str, target: str, tool_id: str = "upstream") -> ToolDependencyConfig:
    return ToolDependencyConfig(
        tool_id=tool_id,
        mappings=[ToolMappingConfig(source_field=source, target_field=target)],
    )


def _make_schema(target_field: str, target_type: str) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            target_field: {"type": target_type},
        },
        "required": [target_field],
    }


def _mock_transformer(json_output: str) -> Any:
    mock = AsyncMock()
    mock.complete = AsyncMock(
        return_value=LLMResponse(
            content=json_output,
            tool_calls=None,
            input_tokens=10,
            output_tokens=5,
            model="mock-model",
        )
    )
    return mock


@pytest.mark.asyncio
async def test_simple_rename_no_llm():
    """String → string rename: programmatic, no LLM call."""
    dep = _make_dep("city", "location")
    schema = _make_schema("location", "string")
    transformer = _mock_transformer('{"location": "Dhaka"}')

    resolved, used_llm, record = await resolve(
        upstream_output={"city": "Dhaka"},
        dependency_config=dep,
        target_input_schema=schema,
        transformer_llm=transformer,
    )

    assert resolved == {"location": "Dhaka"}
    assert used_llm is False
    assert record is None
    transformer.complete.assert_not_called()


@pytest.mark.asyncio
async def test_direct_passthrough_same_field_no_llm():
    """Same field name, same type: programmatic, no LLM call."""
    dep = _make_dep("location", "location")
    schema = _make_schema("location", "string")
    transformer = _mock_transformer('{"location": "London"}')

    resolved, used_llm, record = await resolve(
        upstream_output={"location": "London"},
        dependency_config=dep,
        target_input_schema=schema,
        transformer_llm=transformer,
    )

    assert resolved == {"location": "London"}
    assert used_llm is False
    transformer.complete.assert_not_called()


@pytest.mark.asyncio
async def test_array_passthrough_no_llm():
    """List → array pass-through: programmatic."""
    dep = _make_dep("articles", "articles")
    schema = _make_schema("articles", "array")
    transformer = _mock_transformer('{"articles": []}')

    articles = [{"title": "Test"}]
    resolved, used_llm, _ = await resolve(
        upstream_output={"articles": articles},
        dependency_config=dep,
        target_input_schema=schema,
        transformer_llm=transformer,
    )

    assert resolved == {"articles": articles}
    assert used_llm is False
    transformer.complete.assert_not_called()


@pytest.mark.asyncio
async def test_type_mismatch_triggers_llm():
    """String value to number field: requires LLM transformation."""
    dep = _make_dep("result_str", "value")
    schema = _make_schema("value", "number")
    transformer = _mock_transformer('{"value": 42.0}')

    resolved, used_llm, record = await resolve(
        upstream_output={"result_str": "42"},
        dependency_config=dep,
        target_input_schema=schema,
        transformer_llm=transformer,
    )

    assert used_llm is True
    assert record is not None
    transformer.complete.assert_called_once()


@pytest.mark.asyncio
async def test_missing_source_field_triggers_llm():
    """Source field absent in upstream output: requires LLM."""
    dep = _make_dep("nonexistent_field", "location")
    schema = _make_schema("location", "string")
    transformer = _mock_transformer('{"location": "Unknown"}')

    resolved, used_llm, record = await resolve(
        upstream_output={"other_field": "data"},
        dependency_config=dep,
        target_input_schema=schema,
        transformer_llm=transformer,
    )

    assert used_llm is True
    transformer.complete.assert_called_once()


@pytest.mark.asyncio
async def test_dict_value_to_object_triggers_llm():
    """dict → object is never simple per spec."""
    dep = _make_dep("metadata", "config")
    schema = {
        "type": "object",
        "properties": {"config": {"type": "object"}},
    }
    transformer = _mock_transformer('{"config": {"key": "val"}}')

    resolved, used_llm, _ = await resolve(
        upstream_output={"metadata": {"key": "val"}},
        dependency_config=dep,
        target_input_schema=schema,
        transformer_llm=transformer,
    )

    assert used_llm is True
    transformer.complete.assert_called_once()


@pytest.mark.asyncio
async def test_numeric_passthrough_no_llm():
    """Float value to number field: simple."""
    dep = _make_dep("result", "value")
    schema = _make_schema("value", "number")
    transformer = _mock_transformer('{"value": 125.0}')

    resolved, used_llm, _ = await resolve(
        upstream_output={"result": 125.0},
        dependency_config=dep,
        target_input_schema=schema,
        transformer_llm=transformer,
    )

    assert resolved == {"value": 125.0}
    assert used_llm is False
    transformer.complete.assert_not_called()
