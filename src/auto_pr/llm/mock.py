"""Deterministic Mock LLM Client for offline unit, integration, and regression testing."""

import json
import time
from typing import Any, TypeVar
from pydantic import BaseModel, ValidationError

from auto_pr.llm.client import (
    LLMClient,
    LLMMessage,
    LLMResponse,
    LLMStructuredOutputError,
)

T = TypeVar("T", bound=BaseModel)


class MockLLMCallRecord(BaseModel):
    """Record of an invocation made to the MockLLMClient."""

    prompt: str
    system_instruction: str | None = None
    messages: list[LLMMessage] | None = None
    model: str
    is_structured: bool
    response_model_name: str | None = None


class MockLLMClient(LLMClient):
    """Deterministic Mock LLM Client for testing."""

    def __init__(
        self,
        default_model: str = "mock-model-v1",
        default_text_response: str = "Mock text response",
    ) -> None:
        self.default_model = default_model
        self.default_text_response = default_text_response
        self.text_responses: list[str] = []
        self.structured_responses: list[Any] = []
        self.exception_queue: list[Exception] = []
        self.call_history: list[MockLLMCallRecord] = []

    def queue_text_response(self, text: str) -> None:
        """Queue a sequential text response."""
        self.text_responses.append(text)

    def queue_structured_response(self, response: Any) -> None:
        """Queue a sequential structured response (BaseModel, dict, or JSON str)."""
        self.structured_responses.append(response)

    def queue_exception(self, exc: Exception) -> None:
        """Queue an exception to be raised on the next call."""
        self.exception_queue.append(exc)

    def clear(self) -> None:
        """Clear all queued responses and history."""
        self.text_responses.clear()
        self.structured_responses.clear()
        self.exception_queue.clear()
        self.call_history.clear()

    async def generate_text(
        self,
        prompt: str,
        system_instruction: str | None = None,
        messages: list[LLMMessage] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        """Return a deterministic mock text response."""
        start_time = time.perf_counter()
        target_model = model or self.default_model

        self.call_history.append(
            MockLLMCallRecord(
                prompt=prompt,
                system_instruction=system_instruction,
                messages=messages,
                model=target_model,
                is_structured=False,
            )
        )

        if self.exception_queue:
            raise self.exception_queue.pop(0)

        response_text = (
            self.text_responses.pop(0)
            if self.text_responses
            else self.default_text_response
        )

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        return LLMResponse(
            text=response_text,
            prompt_tokens=len(prompt.split()),
            completion_tokens=len(response_text.split()),
            model_name=target_model,
            duration_ms=duration_ms,
        )

    async def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        system_instruction: str | None = None,
        messages: list[LLMMessage] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> tuple[T, LLMResponse]:
        """Return a deterministic structured response validated against response_model."""
        start_time = time.perf_counter()
        target_model = model or self.default_model

        self.call_history.append(
            MockLLMCallRecord(
                prompt=prompt,
                system_instruction=system_instruction,
                messages=messages,
                model=target_model,
                is_structured=True,
                response_model_name=response_model.__name__,
            )
        )

        if self.exception_queue:
            raise self.exception_queue.pop(0)

        if not self.structured_responses:
            raise LLMStructuredOutputError(
                f"No mock response queued for schema {response_model.__name__}."
            )

        raw_item = self.structured_responses.pop(0)

        parsed_model: T
        raw_text: str

        try:
            if isinstance(raw_item, response_model):
                parsed_model = raw_item
                raw_text = raw_item.model_dump_json()
            elif isinstance(raw_item, dict):
                parsed_model = response_model.model_validate(raw_item)
                raw_text = json.dumps(raw_item)
            elif isinstance(raw_item, str):
                raw_text = raw_item
                parsed_model = response_model.model_validate_json(raw_item)
            else:
                raise LLMStructuredOutputError(
                    f"Unsupported mock item type {type(raw_item)} for model {response_model.__name__}"
                )
        except (ValidationError, json.JSONDecodeError) as err:
            raise LLMStructuredOutputError(
                f"Schema validation failed for model {response_model.__name__}: {err}"
            ) from err

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        metadata = LLMResponse(
            text=raw_text,
            prompt_tokens=len(prompt.split()),
            completion_tokens=len(raw_text.split()),
            model_name=target_model,
            duration_ms=duration_ms,
        )
        return parsed_model, metadata
