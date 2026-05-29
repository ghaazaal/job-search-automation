"""Anthropic / Claude provider."""
import os

from .base import LLMClient


class AnthropicClient(LLMClient):
    def __init__(self, model: str):
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. "
                "Add it to job_hunt/.env or set it in your shell."
            )
        try:
            import anthropic
        except ImportError:
            raise RuntimeError(
                "anthropic package is not installed. "
                "Run: pip install anthropic"
            )
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def complete(self, prompt: str, *,
                 system: str = "",
                 max_tokens: int = 1000) -> str:
        kwargs: dict = dict(
            model=self._model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        if system:
            kwargs["system"] = system
        msg = self._client.messages.create(**kwargs)
        return msg.content[0].text

    @property
    def provider(self) -> str:
        return "anthropic"

    @property
    def model(self) -> str:
        return self._model
