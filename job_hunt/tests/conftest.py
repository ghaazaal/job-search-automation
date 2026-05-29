"""Shared test fixtures and helpers."""
import pytest
from src.llm.base import LLMClient


class MockLLMClient(LLMClient):
    """Deterministic LLM client for tests — returns a preset response."""

    def __init__(self, response: str = "{}"):
        self._response = response

    def complete(self, prompt: str, *,
                 system: str = "",
                 max_tokens: int = 1000) -> str:
        return self._response

    @property
    def provider(self) -> str:
        return "mock"

    @property
    def model(self) -> str:
        return "mock-model"


@pytest.fixture
def mock_llm():
    """Default mock that returns empty JSON — override with MockLLMClient(response=...)."""
    return MockLLMClient("{}")
