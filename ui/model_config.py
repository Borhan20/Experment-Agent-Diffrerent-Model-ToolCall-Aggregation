"""Provider and model catalogue for the UI model selector.

Defines the list of supported providers, their env vars, and the models
available for high-capability (router/tool_selector) and low-cost
(transformer/aggregator) roles.
"""

from __future__ import annotations

import os
from typing import Dict, List

# Provider catalogue: maps provider_id → display info + model lists
PROVIDER_MODELS: Dict[str, Dict] = {
    "gemini": {
        "display": "Google (Gemini)",
        "env_var": "GOOGLE_API_KEY",
        "high_models": [
            "gemini-3.1-pro-preview",    # Latest flagship for complex reasoning/agentic tasks
            "gemini-3-flash-preview",    # High performance, lower latency
            "gemini-2.5-pro",            # Current stable long-context pro model
        ],
        "low_models": [
            "gemini-3.1-flash-lite-preview", # Newest budget-friendly workhorse
            "gemini-2.5-flash",               # Stable price-performance leader
            "gemini-2.5-flash-lite",          # Legacy stable lite model
        ],
        "default_high": "gemini-3.1-pro-preview",
        "default_low": "gemini-3.1-flash-lite-preview",
    },
    "anthropic": {
        "display": "Anthropic (Claude)",
        "env_var": "ANTHROPIC_API_KEY",
        "high_models": [
            "claude-opus-4-6",
            "claude-sonnet-4-6",
        ],
        "low_models": [
            "claude-haiku-4-5-20251001",
            "claude-sonnet-4-6",
        ],
        "default_high": "claude-opus-4-6",
        "default_low": "claude-haiku-4-5-20251001",
    },
    "openai": {
        "display": "OpenAI (GPT)",
        "env_var": "OPENAI_API_KEY",
        "high_models": [
            "gpt-4o",
            "gpt-4-turbo",
            "gpt-4o-mini",
        ],
        "low_models": [
            "gpt-4o-mini",
            "gpt-4o",
        ],
        "default_high": "gpt-4o",
        "default_low": "gpt-4o-mini",
    },
}


def get_available_providers() -> List[str]:
    """Return provider IDs whose API key env var is present and non-empty."""
    return [
        pid
        for pid, info in PROVIDER_MODELS.items()
        if os.environ.get(info["env_var"])
    ]
