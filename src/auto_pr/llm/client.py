"""Provider-independent LLM client abstractions and protocols.

The core application and agents interact exclusively with this protocol,
ensuring total independence from specific model providers (Gemini, OpenAI, etc.).
"""

from abc import ABC, abstractmethod
from typing import Any, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)


class LLMMessage(BaseModel):
    """Normalized message representation for chat-based interactions."""

    role: str = Field(..., description="'system', 'user', or 'assistant'")
    content: str = Field(..., description="Message text content")


class LLMResponse(BaseModel):
    """Metadata and raw text produced by an LLM call."""

    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model_name: str
    duration_ms: int = 0
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class LLMClientError(Exception):
    """Base exception for LLM client failures."""


class LLMAuthenticationError(LLMClientError):
    """Raised when API credentials are missing or rejected."""


class LLMStructuredOutputError(LLMClientError):
    """Raised when LLM output violates schema or fails Pydantic validation."""


class LLMClient(ABC):
    """Abstract provider-independent LLM interface."""

    @abstractmethod
    async def generate_text(
        self,
        prompt: str,
        system_instruction: str | None = None,
        messages: list[LLMMessage] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        """Generate unstructured text from prompt or message sequence."""
        ...

    @abstractmethod
    async def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        system_instruction: str | None = None,
        messages: list[LLMMessage] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> tuple[T, LLMResponse]:
        """Generate structured output validated against a Pydantic schema.

        Returns:
            tuple of (parsed_pydantic_instance, response_metadata)
        Raises:
            LLMStructuredOutputError: If response fails schema validation.
            LLMClientError: On network or provider errors.
        """
        ...
