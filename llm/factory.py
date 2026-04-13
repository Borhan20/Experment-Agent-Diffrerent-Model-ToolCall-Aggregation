"""LLM adapter factory — creates provider adapters from config."""

from __future__ import annotations

import os

from config.loader import ConfigError
from config.models import LLMRoleConfig
from llm.base import LLMAdapter
from llm.openai_adapter import OpenAIAdapter
from llm.anthropic_adapter import AnthropicAdapter
from llm.gemini_adapter import GeminiAdapter

_ENV_VAR_MAP = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GOOGLE_API_KEY",
}


def get_adapter(role_config: LLMRoleConfig) -> LLMAdapter:
    """Create an LLM adapter for a given role configuration.

    Validates that the required API key environment variable is present
    before constructing the adapter.

    Args:
        role_config: LLMRoleConfig with provider, model, and temperature.

    Returns:
        An LLMAdapter instance for the specified provider.

    Raises:
        ConfigError: If the required API key env var is not set.
        ValueError: If the provider is not supported (caught by Pydantic earlier).
    """
    provider = role_config.provider
    required_var = _ENV_VAR_MAP[provider]
    if not os.environ.get(required_var):
        raise ConfigError(
            f"Missing environment variable: {required_var} "
            f"(required for provider '{provider}')"
        )

    if provider == "openai":
        return OpenAIAdapter(model=role_config.model, temperature=role_config.temperature)
    elif provider == "anthropic":
        return AnthropicAdapter(model=role_config.model, temperature=role_config.temperature)
    elif provider == "gemini":
        return GeminiAdapter(model=role_config.model, temperature=role_config.temperature)
    else:
        raise ValueError(f"Unsupported provider: {provider}")
