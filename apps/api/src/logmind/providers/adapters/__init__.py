"""Provider adapters by kind."""

from __future__ import annotations

import httpx

from logmind.providers.adapters.anthropic import AnthropicAdapter
from logmind.providers.adapters.base import Adapter, ProviderConfig
from logmind.providers.adapters.gemini import GeminiAdapter
from logmind.providers.adapters.mock import MockAdapter
from logmind.providers.adapters.ollama import OllamaAdapter
from logmind.providers.adapters.openai import OpenAIAdapter

KINDS: dict[str, type[Adapter]] = {
    "openai": OpenAIAdapter,
    "openai_compatible": OpenAIAdapter,
    "anthropic": AnthropicAdapter,
    "gemini": GeminiAdapter,
    "ollama": OllamaAdapter,
    "mock": MockAdapter,
}

DEFAULT_MODELS = {
    "openai": "gpt-4.1-mini",
    "anthropic": "claude-sonnet-4-5",
    "gemini": "gemini-2.5-flash",
    "ollama": "llama3.1:8b",
    "mock": "logmind-mock",
}

DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "gemini": "https://generativelanguage.googleapis.com",
    "ollama": "http://localhost:11434",
    "mock": "",
}


def adapter_for(config: ProviderConfig, http: httpx.AsyncClient) -> Adapter:
    return KINDS[config.kind](config, http)


__all__ = [
    "DEFAULT_BASE_URLS",
    "DEFAULT_MODELS",
    "KINDS",
    "Adapter",
    "ProviderConfig",
    "adapter_for",
]
