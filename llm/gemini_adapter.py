"""Google Gemini LLM adapter — uses sync SDK methods wrapped in asyncio.to_thread().

google.generativeai uses grpc.aio internally, which binds to whichever event
loop is running when the channel is first used.  Calling the async methods
(_async variants) from a new event loop (e.g. asyncio.run() in a background
thread) causes "Event loop is closed" errors.  Using the sync methods and
offloading them to a thread pool via asyncio.to_thread() avoids this entirely.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import threading
from typing import Any, AsyncIterator, Dict, List, Optional

import google.generativeai as genai

from llm.base import LLMAdapter, LLMResponse, ToolCall, ToolSchema

logger = logging.getLogger(__name__)


def _convert_messages_to_gemini(
    messages: List[Dict[str, str]],
) -> tuple[str, List[Dict[str, Any]]]:
    """Convert OpenAI-style messages to Gemini history + system instruction."""
    non_system = [m for m in messages if m["role"] != "system"]
    system_parts = [m["content"] for m in messages if m["role"] == "system"]

    history: List[Dict[str, Any]] = []
    for msg in non_system:
        gemini_role = "model" if msg["role"] == "assistant" else "user"
        history.append({"role": gemini_role, "parts": [{"text": msg["content"]}]})

    system_instruction = "\n\n".join(system_parts) if system_parts else ""
    return system_instruction, history


class GeminiAdapter:
    """Adapter for the Google Gemini generative AI API."""

    def __init__(self, model: str, temperature: float = 0.0) -> None:
        self.model = model
        self.temperature = temperature
        genai.configure(api_key=os.environ["GOOGLE_API_KEY"])

    def _make_model(
        self,
        generation_config: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Any]] = None,
        system_instruction: str = "",
    ) -> genai.GenerativeModel:
        kwargs: Dict[str, Any] = {"model_name": self.model}
        if generation_config:
            kwargs["generation_config"] = genai.GenerationConfig(**generation_config)
        if tools:
            kwargs["tools"] = tools
        if system_instruction:
            kwargs["system_instruction"] = system_instruction
        return genai.GenerativeModel(**kwargs)

    async def complete(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[ToolSchema]] = None,
        structured_output_schema: Optional[Dict[str, Any]] = None,
    ) -> LLMResponse:
        system_instruction, history = _convert_messages_to_gemini(messages)

        if not history:
            raise ValueError("At least one user message required")

        last_message = history[-1]
        chat_history = history[:-1]

        if structured_output_schema is not None:
            # Inject the required schema into the message so the model knows
            # exactly which fields to produce (response_mime_type only forces
            # JSON output, not the specific structure).
            schema_str = json.dumps(structured_output_schema, indent=2)
            schema_suffix = (
                f"\n\nYou MUST return a JSON object that exactly matches this schema:\n"
                f"{schema_str}\n\n"
                "Return ONLY the JSON object — no markdown fences, no explanation."
            )
            original_text = last_message["parts"][0]["text"] if last_message["parts"] else ""
            augmented_parts = [{"text": original_text + schema_suffix}]

            model = self._make_model(
                generation_config={
                    "temperature": self.temperature,
                    "response_mime_type": "application/json",
                },
                system_instruction=system_instruction,
            )
            chat = model.start_chat(history=chat_history)

            # Use sync send_message in a thread to avoid grpc.aio loop binding
            response = await asyncio.to_thread(chat.send_message, augmented_parts)
            usage = response.usage_metadata
            return LLMResponse(
                content=response.text or "",
                tool_calls=None,
                input_tokens=usage.prompt_token_count if usage else 0,
                output_tokens=usage.candidates_token_count if usage else 0,
                model=self.model,
            )

        if tools is not None:
            gemini_tools = [
                genai.protos.Tool(
                    function_declarations=[
                        genai.protos.FunctionDeclaration(
                            name=t.name,
                            description=t.description,
                            parameters=_schema_to_gemini_schema(t.input_schema),
                        )
                    ]
                )
                for t in tools
            ]
            model = self._make_model(
                generation_config={"temperature": self.temperature},
                tools=gemini_tools,
                system_instruction=system_instruction,
            )
            chat = model.start_chat(history=chat_history)
            response = await asyncio.to_thread(chat.send_message, last_message["parts"])

            tool_call_list = []
            for candidate in response.candidates:
                for part in candidate.content.parts:
                    if part.function_call:
                        fc = part.function_call
                        tool_call_list.append(
                            ToolCall(
                                tool_name=fc.name,
                                arguments=dict(fc.args),
                                call_id=None,
                            )
                        )
            usage = response.usage_metadata
            return LLMResponse(
                content=response.text or "",
                tool_calls=tool_call_list or None,
                input_tokens=usage.prompt_token_count if usage else 0,
                output_tokens=usage.candidates_token_count if usage else 0,
                model=self.model,
            )

        # Plain text completion
        model = self._make_model(
            generation_config={"temperature": self.temperature},
            system_instruction=system_instruction,
        )
        chat = model.start_chat(history=chat_history)
        response = await asyncio.to_thread(chat.send_message, last_message["parts"])
        usage = response.usage_metadata
        return LLMResponse(
            content=response.text or "",
            tool_calls=None,
            input_tokens=usage.prompt_token_count if usage else 0,
            output_tokens=usage.candidates_token_count if usage else 0,
            model=self.model,
        )

    async def stream(
        self,
        messages: List[Dict[str, str]],
    ) -> AsyncIterator[str]:
        system_instruction, history = _convert_messages_to_gemini(messages)
        if not history:
            raise ValueError("At least one user message required")

        last_message = history[-1]
        chat_history = history[:-1]

        model = self._make_model(
            generation_config={"temperature": self.temperature},
            system_instruction=system_instruction,
        )
        chat = model.start_chat(history=chat_history)
        self._last_stream_input_tokens = None
        self._last_stream_output_tokens = None

        # Run the sync streaming iterator in a background thread.
        # Chunks are passed through a SimpleQueue; asyncio.to_thread(q.get)
        # blocks in the thread pool without blocking the event loop.
        chunk_queue: queue.SimpleQueue = queue.SimpleQueue()

        def _sync_stream() -> None:
            try:
                for chunk in chat.send_message(last_message["parts"], stream=True):
                    chunk_queue.put(chunk)
            except Exception as exc:
                chunk_queue.put(exc)
            finally:
                chunk_queue.put(None)  # sentinel

        threading.Thread(target=_sync_stream, daemon=True).start()

        while True:
            item = await asyncio.to_thread(chunk_queue.get)
            if item is None:
                break
            if isinstance(item, Exception):
                raise item
            if item.text:
                yield item.text
            if item.usage_metadata:
                self._last_stream_input_tokens = item.usage_metadata.prompt_token_count
                self._last_stream_output_tokens = item.usage_metadata.candidates_token_count


def _schema_to_gemini_schema(schema: Dict[str, Any]) -> genai.protos.Schema:
    """Convert a JSON Schema dict to a Gemini Schema proto."""
    type_map = {
        "string": genai.protos.Type.STRING,
        "number": genai.protos.Type.NUMBER,
        "integer": genai.protos.Type.INTEGER,
        "boolean": genai.protos.Type.BOOLEAN,
        "array": genai.protos.Type.ARRAY,
        "object": genai.protos.Type.OBJECT,
    }
    schema_type = type_map.get(schema.get("type", "object"), genai.protos.Type.OBJECT)
    properties = {}
    for prop_name, prop_schema in schema.get("properties", {}).items():
        prop_type = type_map.get(prop_schema.get("type", "string"), genai.protos.Type.STRING)
        properties[prop_name] = genai.protos.Schema(
            type=prop_type,
            description=prop_schema.get("description", ""),
        )
    return genai.protos.Schema(
        type=schema_type,
        properties=properties,
        required=schema.get("required", []),
    )
