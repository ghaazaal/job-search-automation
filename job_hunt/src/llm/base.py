"""Abstract LLM client interface.

All provider implementations must subclass LLMClient and implement `complete`.
Agents depend only on this interface — never on a specific SDK.
"""
from abc import ABC, abstractmethod


class LLMClient(ABC):
    """Single-method interface for all LLM providers."""

    @abstractmethod
    def complete(self, prompt: str, *,
                 system: str = "",
                 max_tokens: int = 1000) -> str:
        """Send a prompt and return the text response.

        Args:
            prompt:     The user message.
            system:     Optional system/instruction prefix.
            max_tokens: Upper bound on response length.

        Returns:
            The model's text response as a plain string.

        Raises:
            RuntimeError: On any provider-level failure.
        """

    @property
    @abstractmethod
    def provider(self) -> str:
        """Provider identifier, e.g. 'anthropic', 'groq', 'gemini'."""

    @property
    @abstractmethod
    def model(self) -> str:
        """Model name as configured, e.g. 'claude-sonnet-4-6'."""

    def __repr__(self) -> str:
        return f"<LLMClient provider={self.provider!r} model={self.model!r}>"
