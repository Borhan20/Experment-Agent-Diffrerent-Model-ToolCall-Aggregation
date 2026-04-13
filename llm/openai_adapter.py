"""OpenAI LLM adapter."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from openai import AsyncOpenAI

from llm.base import LLMAdapter, LLMResponse, ToolCall, ToolSchema

logger = logging.getLogger(__name__)


class OpenAIAdapter:
    """Adapter for the OpenAI chat completions API."""

    def __init__(self, model: str, temperature: float = 0.0) -> None:
        self.model = model
        self.temperature = temperature
        self._client = AsyncOpenAI()  # reads OPENAI_API_KEY from env

    async def complete(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[ToolSchema]] = None,
        structured_output_schema: Optional[Dict[str, Any]] = None,
    ) -> LLMResponse:
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }

        if structured_output_schema is not None:
            # JSON schema output mode
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "output",
                    "schema": structured_output_schema,
                    "strict": False,
                },
            }
            response = await self._client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content or ""
            return LLMResponse(
                content=content,
                tool_calls=None,
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
                model=response.model,
            )

        if tools is not None:
            # Function-calling mode
            openai_tools = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in tools
            ]
            kwargs["tools"] = openai_tools
            response = await self._client.chat.completions.create(**kwargs)
            msg = response.choices[0].message
            parsed_calls: Optional[List[ToolCall]] = None
            if msg.tool_calls:
                parsed_calls = [
                    ToolCall(
                        tool_name=tc.function.name,
                        arguments=json.loads(tc.function.arguments),
                        call_id=tc.id,
                    )
                    for tc in msg.tool_calls
                ]
            return LLMResponse(
                content=msg.content or "",
                tool_calls=parsed_calls,
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
                model=response.model,
            )

        # Plain text completion
        response = await self._client.chat.completions.create(**kwargs)
        return LLMResponse(
            content=response.choices[0].message.content or "",
            tool_calls=None,
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            model=response.model,
        )

    async def stream(
        self,
        messages: List[Dict[str, str]],
    ) -> AsyncIterator[str]:
        self._last_stream_input_tokens = None
        self._last_stream_output_tokens = None
        stream = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            stream=True,
            stream_options={"include_usage": True},
        )
        async for chunk in stream:
            # Final chunk from OpenAI carries usage when stream_options include_usage is set
            if chunk.usage is not None:
                self._last_stream_input_tokens = chunk.usage.prompt_tokens
                self._last_stream_output_tokens = chunk.usage.completion_tokens
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content
