"""Google Gemini LLM client implementing the LLMClient protocol.

Keeps all Gemini-specific SDK imports, types, and logic strictly contained
inside this provider module.
"""

import os
import time
from typing import TypeVar
from pydantic import BaseModel, ValidationError

from auto_pr.config import settings
from auto_pr.llm.client import (
    LLMClient,
    LLMMessage,
    LLMResponse,
    LLMClientError,
    LLMAuthenticationError,
    LLMStructuredOutputError,
)

T = TypeVar("T", bound=BaseModel)


class GeminiLLMClient(LLMClient):
    """Google Gemini client backed by official google-genai SDK."""

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str | None = None,
    ) -> None:
        self.api_key = api_key or settings.gemini_api_key or os.environ.get("GEMINI_API_KEY")
        self.default_model = default_model or settings.model_name
        self._client = None

    def _get_client(self):
        """Lazy-initialize google-genai client."""
        if not self.api_key:
            raise LLMAuthenticationError(
                "Gemini API key is not configured. Set AUTO_PR_GEMINI_API_KEY or GEMINI_API_KEY."
            )
        if self._client is None:
            try:
                from google import genai

                self._client = genai.Client(api_key=self.api_key)
            except Exception as err:
                raise LLMClientError(f"Failed to initialize Google GenAI client: {err}") from err
        return self._client

    async def generate_text(
        self,
        prompt: str,
        system_instruction: str | None = None,
        messages: list[LLMMessage] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        """Generate text using Gemini models via google-genai async client."""
        client = self._get_client()
        target_model = model or self.default_model
        start_time = time.perf_counter()

        try:
            from google.genai import types

            config = types.GenerateContentConfig(
                temperature=temperature,
                system_instruction=system_instruction,
            )

            # Assemble contents
            contents: Any
            if messages:
                contents = [
                    types.Content(
                        role="user" if m.role in ("user", "system") else "model",
                        parts=[types.Part.from_text(text=m.content)],
                    )
                    for m in messages
                ]
                if prompt:
                    contents.append(
                        types.Content(
                            role="user",
                            parts=[types.Part.from_text(text=prompt)],
                        )
                    )
            else:
                contents = prompt

            response = await client.aio.models.generate_content(
                model=target_model,
                contents=contents,
                config=config,
            )

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            text_output = response.text or ""

            prompt_tokens = 0
            completion_tokens = 0
            if response.usage_metadata:
                prompt_tokens = response.usage_metadata.prompt_token_count or 0
                completion_tokens = response.usage_metadata.candidates_token_count or 0

            return LLMResponse(
                text=text_output,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model_name=target_model,
                duration_ms=duration_ms,
            )
        except LLMClientError:
            raise
        except Exception as err:
            raise LLMClientError(f"Gemini generate_text failed: {err}") from err

    async def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        system_instruction: str | None = None,
        messages: list[LLMMessage] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> tuple[T, LLMResponse]:
        """Generate structured output validated against Pydantic schema using Gemini."""
        client = self._get_client()
        target_model = model or self.default_model
        start_time = time.perf_counter()

        try:
            from google.genai import types

            config = types.GenerateContentConfig(
                temperature=temperature,
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=response_model,
            )

            contents: Any
            if messages:
                contents = [
                    types.Content(
                        role="user" if m.role in ("user", "system") else "model",
                        parts=[types.Part.from_text(text=m.content)],
                    )
                    for m in messages
                ]
                if prompt:
                    contents.append(
                        types.Content(
                            role="user",
                            parts=[types.Part.from_text(text=prompt)],
                        )
                    )
            else:
                contents = prompt

            response = await client.aio.models.generate_content(
                model=target_model,
                contents=contents,
                config=config,
            )

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            text_output = response.text or ""

            prompt_tokens = 0
            completion_tokens = 0
            if response.usage_metadata:
                prompt_tokens = response.usage_metadata.prompt_token_count or 0
                completion_tokens = response.usage_metadata.candidates_token_count or 0

            metadata = LLMResponse(
                text=text_output,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model_name=target_model,
                duration_ms=duration_ms,
            )

            # Strict Pydantic validation
            try:
                parsed = response_model.model_validate_json(text_output)
            except ValidationError as v_err:
                raise LLMStructuredOutputError(
                    f"Gemini output failed schema validation for {response_model.__name__}: {v_err}"
                ) from v_err

            return parsed, metadata
        except (LLMClientError, LLMStructuredOutputError):
            raise
        except Exception as err:
            raise LLMClientError(f"Gemini generate_structured failed: {err}") from err
