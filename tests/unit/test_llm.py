"""Unit tests for provider-independent LLM client abstractions."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from pydantic import BaseModel, Field

from auto_pr.llm.client import (
    LLMClient,
    LLMMessage,
    LLMResponse,
    LLMAuthenticationError,
    LLMStructuredOutputError,
)
from auto_pr.llm.mock import MockLLMClient
from auto_pr.llm.gemini import GeminiLLMClient


class SampleSchema(BaseModel):
    name: str
    count: int = Field(gt=0)


@pytest.mark.asyncio
async def test_mock_llm_text_generation() -> None:
    client = MockLLMClient(default_text_response="Sample response")
    res = await client.generate_text("Hello")
    assert res.text == "Sample response"
    assert res.model_name == "mock-model-v1"
    assert len(client.call_history) == 1


@pytest.mark.asyncio
async def test_mock_llm_valid_structured_response() -> None:
    client = MockLLMClient()
    client.queue_structured_response({"name": "alpha", "count": 10})

    parsed, meta = await client.generate_structured("Generate item", SampleSchema)
    assert isinstance(parsed, SampleSchema)
    assert parsed.name == "alpha"
    assert parsed.count == 10
    assert meta.model_name == "mock-model-v1"


@pytest.mark.asyncio
async def test_mock_llm_malformed_json_rejection() -> None:
    client = MockLLMClient()
    client.queue_structured_response("INVALID_NOT_A_JSON{broken")

    with pytest.raises(LLMStructuredOutputError) as exc_info:
        await client.generate_structured("broken", SampleSchema)
    assert "Schema validation failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_mock_llm_missing_required_fields_rejection() -> None:
    client = MockLLMClient()
    # Missing required field 'name' and invalid 'count'
    client.queue_structured_response({"count": -5})

    with pytest.raises(LLMStructuredOutputError) as exc_info:
        await client.generate_structured("missing fields", SampleSchema)
    assert "Schema validation failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_gemini_client_requires_api_key() -> None:
    """Verify Gemini client raises LLMAuthenticationError when no API key is provided."""
    client = GeminiLLMClient(api_key=None)
    # Clear any env var temporarily
    with patch.dict("os.environ", {}, clear=True):
        client.api_key = None
        with pytest.raises(LLMAuthenticationError) as exc_info:
            await client.generate_text("Test prompt")
        assert "Gemini API key is not configured" in str(exc_info.value)


@pytest.mark.asyncio
async def test_gemini_client_contract_with_mocked_sdk() -> None:
    """Verify GeminiLLMClient conforms to LLMClient contract using a mocked GenAI SDK."""
    client = GeminiLLMClient(api_key="fake-key-for-contract-test")

    mock_genai_client = MagicMock()
    mock_genai_client.aio.models.generate_content = AsyncMock()

    # Mock text response
    mock_response = MagicMock()
    mock_response.text = '{"name": "mocked-gemini", "count": 42}'
    mock_response.usage_metadata.prompt_token_count = 15
    mock_response.usage_metadata.candidates_token_count = 10
    mock_genai_client.aio.models.generate_content.return_value = mock_response

    with patch("google.genai.Client", return_value=mock_genai_client):
        parsed, meta = await client.generate_structured("prompt", SampleSchema)
        assert parsed.name == "mocked-gemini"
        assert parsed.count == 42
        assert meta.prompt_tokens == 15
        assert meta.completion_tokens == 10
        assert mock_genai_client.aio.models.generate_content.called
