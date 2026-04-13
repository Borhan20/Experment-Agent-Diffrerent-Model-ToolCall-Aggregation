"""Anthropic LLM adapter."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

import anthropic

from llm.base import LLMAdapter, LLMResponse, ToolCall, ToolSchema

logger = logging.getLogger(__name__)


class AnthropicAdapter:
    """Adapter for the Anthropic Messages API."""

    def __init__(self, model: str, temperature: float = 0.0) -> None:
        self.model = model
        self.temperature = temperature
        self._client = anthropic.AsyncAnthropic()  # reads ANTHROPIC_API_KEY from env

    async def complete(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[ToolSchema]] = None,
        structured_output_schema: Optional[Dict[str, Any]] = None,
    ) -> LLMResponse:
        # Anthropic requires system messages to be passed separately
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        user_messages = [m for m in messages if m["role"] != "system"]
        system_prompt = "\n\n".join(system_parts) if system_parts else anthropic.NOT_GIVEN

        if structured_output_schema is not None:
            # Force tool use with a schema-matching tool to get structured JSON output
            output_tool = {
                "name": "structured_output",
                "description": "Return the structured output matching the required schema.",
                "input_schema": structured_output_schema,
            }
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=4096,
                temperature=self.temperature,
                system=system_prompt,
                messages=user_messages,
                tools=[output_tool],
                tool_choice={"type": "tool", "name": "structured_output"},
            )
            content = ""
            for block in response.content:
                if block.type == "tool_use" and block.name == "structured_output":
                    content = json.dumps(block.input)
                    break
            return LLMResponse(
                content=content,
                tool_calls=None,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                model=response.model,
            )

        if tools is not None:
            anthropic_tools = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in tools
            ]
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=4096,
                temperature=self.temperature,
                system=system_prompt,
                messages=user_messages,
                tools=anthropic_tools,
            )
            text_content = ""
            parsed_calls: Optional[List[ToolCall]] = None
            tool_call_list = []
            for block in response.content:
                if block.type == "text":
                    text_content += block.text
                elif block.type == "tool_use":
                    tool_call_list.append(
                        ToolCall(
                            tool_name=block.name,
                            arguments=block.input,
                            call_id=block.id,
                        )
                    )
            if tool_call_list:
                parsed_calls = tool_call_list
            return LLMResponse(
                content=text_content,
                tool_calls=parsed_calls,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                model=response.model,
            )

        # Plain text completion
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=4096,
            temperature=self.temperature,
            system=system_prompt,
            messages=user_messages,
        )
        text_content = "".join(
            block.text for block in response.content if block.type == "text"
        )
        return LLMResponse(
            content=text_content,
            tool_calls=None,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
        )

    async def stream(
        self,
        messages: List[Dict[str, str]],
    ) -> AsyncIterator[str]:
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        user_messages = [m for m in messages if m["role"] != "system"]
        system_prompt = "\n\n".join(system_parts) if system_parts else anthropic.NOT_GIVEN

        async with self._client.messages.stream(
            model=self.model,
            max_tokens=4096,
            temperature=self.temperature,
            system=system_prompt,
            messages=user_messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text
            # Capture exact token counts after stream is fully consumed
            try:
                final_msg = await stream.get_final_message()
                self._last_stream_input_tokens = final_msg.usage.input_tokens
                self._last_stream_output_tokens = final_msg.usage.output_tokens
            except Exception:
                self._last_stream_input_tokens = None
                self._last_stream_output_tokens = None
