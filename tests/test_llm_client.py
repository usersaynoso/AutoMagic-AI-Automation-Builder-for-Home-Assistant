"""Tests for llm_client module."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.automagic.llm_client import (
    LLMClient,
    LLMConnectionError,
    LLMResponseError,
    fetch_models,
)


def _make_completion_response(content: str, model: str = "test-model") -> dict:
    """Build a minimal OpenAI-format completion response."""
    return {
        "id": "test",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


class FakeResponse:
    """Minimal mock for aiohttp response as an async context manager."""

    def __init__(self, status: int, body: dict | str):
        self.status = status
        self._body = body

    async def json(self):
        if isinstance(self._body, str):
            return json.loads(self._body)
        return self._body

    async def text(self):
        if isinstance(self._body, str):
            return self._body
        return json.dumps(self._body)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class FakeSession:
    """Minimal mock aiohttp session."""

    def __init__(self, response: FakeResponse):
        self._response = response

    def post(self, url, **kwargs):
        return self._response

    def get(self, url, **kwargs):
        return self._response

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_complete_success():
    """Test successful completion with valid JSON response."""
    content = json.dumps({"yaml": "alias: Test", "summary": "A test automation"})
    resp = FakeResponse(200, _make_completion_response(content))
    session = FakeSession(resp)

    client = LLMClient(
        endpoint_url="http://localhost:11434",
        model="llama3",
        session=session,
    )
    result = await client.complete([{"role": "user", "content": "test"}])
    assert result["yaml"] == "alias: Test"
    assert result["summary"] == "A test automation"


@pytest.mark.asyncio
async def test_complete_strips_markdown_fences():
    """Test that markdown code fences are stripped before parsing."""
    raw = '```json\n{"yaml": "alias: Fenced", "summary": "fenced"}\n```'
    resp = FakeResponse(200, _make_completion_response(raw))
    session = FakeSession(resp)

    client = LLMClient(
        endpoint_url="http://localhost:11434",
        model="llama3",
        session=session,
    )
    result = await client.complete([{"role": "user", "content": "test"}])
    assert result["yaml"] == "alias: Fenced"


@pytest.mark.asyncio
async def test_complete_http_error():
    """Test that non-200 status raises LLMResponseError."""
    resp = FakeResponse(500, "Internal Server Error")
    session = FakeSession(resp)

    client = LLMClient(
        endpoint_url="http://localhost:11434",
        model="llama3",
        session=session,
    )
    with pytest.raises(LLMResponseError, match="HTTP 500"):
        await client.complete([{"role": "user", "content": "test"}])


@pytest.mark.asyncio
async def test_complete_empty_choices():
    """Test that missing choices raises LLMResponseError."""
    resp = FakeResponse(200, {"choices": []})
    session = FakeSession(resp)

    client = LLMClient(
        endpoint_url="http://localhost:11434",
        model="llama3",
        session=session,
    )
    with pytest.raises(LLMResponseError, match="No choices"):
        await client.complete([{"role": "user", "content": "test"}])


@pytest.mark.asyncio
async def test_complete_invalid_json_content():
    """Test that non-JSON content raises LLMResponseError."""
    resp = FakeResponse(200, _make_completion_response("This is not JSON"))
    session = FakeSession(resp)

    client = LLMClient(
        endpoint_url="http://localhost:11434",
        model="llama3",
        session=session,
    )
    with pytest.raises(LLMResponseError, match="Failed to parse"):
        await client.complete([{"role": "user", "content": "test"}])


@pytest.mark.asyncio
async def test_complete_null_model_handled():
    """Test that null model field in response (LM Studio quirk) is handled."""
    content = json.dumps({"yaml": "alias: Test", "summary": "test"})
    resp = FakeResponse(200, _make_completion_response(content, model=None))
    session = FakeSession(resp)

    client = LLMClient(
        endpoint_url="http://localhost:11434",
        model="llama3",
        session=session,
    )
    result = await client.complete([{"role": "user", "content": "test"}])
    assert result["yaml"] == "alias: Test"


@pytest.mark.asyncio
async def test_from_config():
    """Test creating client from config dict."""
    config = {
        "endpoint_url": "http://localhost:1234",
        "model": "gpt-4o",
        "max_tokens": 4096,
        "request_timeout": 480,
        "temperature": 0.5,
    }
    client = LLMClient.from_config(config)
    assert client._endpoint_url == "http://localhost:1234"
    assert client._model == "gpt-4o"
    assert client._max_tokens == 4096
    assert client._request_timeout == 480
    assert client._temperature == 0.5


@pytest.mark.asyncio
async def test_fetch_models_openai_format():
    """Test fetching models from OpenAI-format endpoint."""
    openai_resp = FakeResponse(
        200,
        {"data": [{"id": "gpt-4o"}, {"id": "gpt-3.5-turbo"}]},
    )
    session = FakeSession(openai_resp)
    models = await fetch_models("http://localhost:1234", session=session)
    assert "gpt-3.5-turbo" in models
    assert "gpt-4o" in models


@pytest.mark.asyncio
async def test_fetch_models_ollama_format():
    """Test fetching models from Ollama-format endpoint after OpenAI fails."""

    class DualSession:
        """Session that fails on /v1/models but succeeds on /api/tags."""
        def get(self, url, **kwargs):
            if "/v1/models" in url:
                return FakeResponse(404, "Not found")
            return FakeResponse(
                200,
                {"models": [{"name": "llama3:latest"}, {"name": "codellama:7b"}]},
            )
        async def close(self):
            pass

    models = await fetch_models("http://localhost:11434", session=DualSession())
    assert "llama3:latest" in models
    assert "codellama:7b" in models


@pytest.mark.asyncio
async def test_fetch_models_both_fail():
    """Test that empty list is returned when both endpoints fail."""

    class FailSession:
        def get(self, url, **kwargs):
            return FakeResponse(500, "error")
        async def close(self):
            pass

    models = await fetch_models("http://localhost:11434", session=FailSession())
    assert models == []


@pytest.mark.asyncio
async def test_probe_generation_status_reports_active_ollama_model():
    """Ollama /api/ps should surface active model status."""
    resp = FakeResponse(200, {"models": [{"name": "qwen2.5:14b"}]})
    session = FakeSession(resp)

    client = LLMClient(
        endpoint_url="http://localhost:11434",
        model="qwen2.5:14b",
        session=session,
    )
    status = await client.probe_generation_status()

    assert status["available"] is True
    assert status["backend"] == "ollama"
    assert status["active"] is True
    assert "still running" in status["message"]


@pytest.mark.asyncio
async def test_probe_generation_status_handles_non_ollama_endpoint():
    """Non-Ollama endpoints should simply report no backend probe support."""
    resp = FakeResponse(404, "Not found")
    session = FakeSession(resp)

    client = LLMClient(
        endpoint_url="http://localhost:1234",
        model="gpt-4o-mini",
        session=session,
    )
    status = await client.probe_generation_status()

    assert status["available"] is False
