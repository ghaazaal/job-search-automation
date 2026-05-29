"""LLM client factory.

Resolution order for provider and model:
  1. Environment variables LLM_PROVIDER / LLM_MODEL  (highest priority)
  2. config.yaml  llm.provider / llm.model
  3. Built-in defaults per provider                  (lowest priority)

Usage:
    from src.llm.factory import get_client
    llm = get_client(config)          # build once in main.py
    response = llm.complete(prompt)   # use everywhere
"""
import os

from .base import LLMClient

_PROVIDER_DEFAULTS = {
    "anthropic": "claude-sonnet-4-6",
    "groq":      "llama-3.3-70b-versatile",
    "gemini":    "gemini-1.5-flash",
}

_SUPPORTED = sorted(_PROVIDER_DEFAULTS)


def get_client(config: dict) -> LLMClient:
    """Build and return the configured LLM client.

    Raises:
        ValueError:   Unknown provider name.
        RuntimeError: Missing API key or package not installed.
    """
    llm_cfg = config.get("llm", {})

    provider = (
        os.environ.get("LLM_PROVIDER")
        or llm_cfg.get("provider", "anthropic")
    ).lower().strip()

    model = (
        os.environ.get("LLM_MODEL")
        or llm_cfg.get("model")
        or _PROVIDER_DEFAULTS.get(provider, "")
    )

    if provider == "anthropic":
        from .anthropic_client import AnthropicClient
        return AnthropicClient(model)

    if provider == "groq":
        from .groq_client import GroqClient
        return GroqClient(model)

    if provider == "gemini":
        from .gemini_client import GeminiClient
        return GeminiClient(model)

    raise ValueError(
        f"Unknown LLM provider: {provider!r}. "
        f"Supported: {', '.join(_SUPPORTED)}. "
        "Set LLM_PROVIDER in .env or config.yaml llm.provider."
    )
