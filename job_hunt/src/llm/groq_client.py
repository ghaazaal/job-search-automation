"""Groq provider (free tier — Llama 3.3 70B).

Sign up at https://console.groq.com and set GROQ_API_KEY.
"""
import os

from .base import LLMClient


class GroqClient(LLMClient):
    def __init__(self, model: str):
        api_key = os.environ.get("GROQ_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. "
                "Sign up at https://console.groq.com and add it to job_hunt/.env."
            )
        try:
            from groq import Groq
        except ImportError:
            raise RuntimeError(
                "groq package is not installed. "
                "Run: pip install groq"
            )
        self._client = Groq(api_key=api_key)
        self._model = model

    def complete(self, prompt: str, *,
                 system: str = "",
                 max_tokens: int = 1000) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=messages,
        )
        return resp.choices[0].message.content

    @property
    def provider(self) -> str:
        return "groq"

    @property
    def model(self) -> str:
        return self._model
