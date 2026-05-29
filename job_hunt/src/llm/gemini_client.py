"""Google Gemini provider — structure ready, not yet enabled.

To enable:
  1. pip install google-generativeai
  2. Set GEMINI_API_KEY in job_hunt/.env
  3. Set LLM_PROVIDER=gemini in .env or config.yaml
  4. Implement the complete() method below using google.generativeai.

Sign up at https://aistudio.google.com (free tier: 1M tokens/day on Flash).
"""
import os

from .base import LLMClient


class GeminiClient(LLMClient):
    def __init__(self, model: str):
        # Validate key presence early so the error is clear
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. "
                "Get one at https://aistudio.google.com and add it to job_hunt/.env."
            )
        try:
            import google.generativeai as genai  # noqa: F401
        except ImportError:
            raise RuntimeError(
                "google-generativeai package is not installed. "
                "Run: pip install google-generativeai"
            )
        self._model = model
        self._api_key = api_key
        # TODO: initialise the Gemini client here once enabled
        raise NotImplementedError(
            "Gemini support is scaffolded but not yet implemented. "
            "Use LLM_PROVIDER=anthropic or LLM_PROVIDER=groq for now."
        )

    def complete(self, prompt: str, *,
                 system: str = "",
                 max_tokens: int = 1000) -> str:
        # TODO: implement using google.generativeai
        # import google.generativeai as genai
        # genai.configure(api_key=self._api_key)
        # model = genai.GenerativeModel(self._model, system_instruction=system)
        # resp = model.generate_content(prompt,
        #     generation_config={"max_output_tokens": max_tokens})
        # return resp.text
        raise NotImplementedError

    @property
    def provider(self) -> str:
        return "gemini"

    @property
    def model(self) -> str:
        return self._model
