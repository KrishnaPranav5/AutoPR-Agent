"""LLM client abstractions and provider implementations."""

from auto_pr.llm.client import (
    LLMClient,
    LLMMessage,
    LLMResponse,
    LLMClientError,
    LLMAuthenticationError,
    LLMStructuredOutputError,
)
from auto_pr.llm.mock import MockLLMClient
from auto_pr.llm.gemini import GeminiLLMClient

__all__ = [
    "LLMClient",
    "LLMMessage",
    "LLMResponse",
    "LLMClientError",
    "LLMAuthenticationError",
    "LLMStructuredOutputError",
    "MockLLMClient",
    "GeminiLLMClient",
]
