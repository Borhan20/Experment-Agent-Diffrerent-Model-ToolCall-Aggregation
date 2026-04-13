"""LLM adapter protocol and shared data types."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional, Protocol, runtime_checkable


@dataclass
class ToolSchema:
    """Schema definition for a tool offered to an LLM."""
    name: str
    description: str
    input_schema: Dict[str, Any]  # JSON Schema object


@dataclass
class ToolCall:
    """A tool call returned by the LLM."""
    tool_name: str
    arguments: Dict[str, Any]  # parsed from provider's JSON
    call_id: Optional[str] = None


@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""
    content: str                           # text content (empty if tool_calls present)
    tool_calls: Optional[List[ToolCall]]   # populated when tools were called
    input_tokens: int
    output_tokens: int
    model: str


@dataclass
class LLMCallRecord:
    """Metadata record for one LLM API call, used for cost observability."""
    role: str        # "router" | "tool_selector" | "transformer" | "aggregator"
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "timestamp": self.timestamp,
        }


@runtime_checkable
class LLMAdapter(Protocol):
    """Protocol that all provider adapters must implement."""

    async def complete(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[ToolSchema]] = None,
        structured_output_schema: Optional[Dict[str, Any]] = None,
    ) -> LLMResponse:
        """Invoke the LLM for a single completion.

        Args:
            messages: List of {"role": ..., "content": ...} dicts.
            tools: If provided, offer these tools for function-calling.
            structured_output_schema: If provided, force JSON output matching schema.
                                       Mutually exclusive with tools.

        Returns:
            LLMResponse with content/tool_calls and token counts.
        """
        ...

    async def stream(
        self,
        messages: List[Dict[str, str]],
    ) -> AsyncIterator[str]:
        """Stream text completion token-by-token.

        Args:
            messages: List of {"role": ..., "content": ...} dicts.

        Yields:
            String chunks as they are produced.
        """
        ...
