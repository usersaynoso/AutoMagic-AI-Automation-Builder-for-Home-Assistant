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

    def __init__(self, response: FakeResponse | list[FakeResponse]):
        self._responses = response if isinstance(response, list) else [response]
        self.last_post = None
        self.last_get = None
        self.post_calls = []
        self.get_calls = []

    def _next_response(self, calls: list[dict], responses: list[FakeResponse]) -> FakeResponse:
        index = min(len(calls), len(responses) - 1)
        return responses[index]

    def post(self, url, **kwargs):
        self.last_post = {"url": url, "kwargs": kwargs}
        self.post_calls.append(self.last_post)
        return self._next_response(self.post_calls[:-1], self._responses)

    def get(self, url, **kwargs):
        self.last_get = {"url": url, "kwargs": kwargs}
        self.get_calls.append(self.last_get)
        return self._next_response(self.get_calls[:-1], self._responses)

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_complete_success():
    """Test successful completion with valid JSON response."""
    content = json.dumps(
        {
            "yaml": "alias: Test",
            "summary": "A test automation",
            "needs_clarification": False,
            "clarifying_questions": [],
        }
    )
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
    assert result["needs_clarification"] is False
    assert result["clarifying_questions"] == []
    assert session.last_post["kwargs"]["json"]["response_format"] == {
        "type": "json_object"
    }


@pytest.mark.asyncio
async def test_complete_sends_bearer_token_for_openai_style_services():
    """Configured API keys should be forwarded as bearer auth headers."""
    content = json.dumps(
        {
            "yaml": "alias: Test",
            "summary": "A test automation",
            "needs_clarification": False,
            "clarifying_questions": [],
        }
    )
    resp = FakeResponse(200, _make_completion_response(content))
    session = FakeSession(resp)

    client = LLMClient(
        endpoint_url="https://api.openai.com",
        model="gpt-4o-mini",
        api_key="sk-test",
        session=session,
    )
    await client.complete([{"role": "user", "content": "test"}])

    assert session.last_post["kwargs"]["headers"] == {
        "Authorization": "Bearer sk-test"
    }


@pytest.mark.asyncio
async def test_complete_strips_markdown_fences():
    """Test that markdown code fences are stripped before parsing."""
    raw = (
        '```json\n{"yaml": "alias: Fenced", "summary": "fenced", '
        '"needs_clarification": false, "clarifying_questions": []}\n```'
    )
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
async def test_complete_retries_transient_http_errors_before_succeeding():
    """Transient upstream failures should be retried silently."""
    content = json.dumps(
        {
            "yaml": "alias: Test",
            "summary": "A test automation",
            "needs_clarification": False,
            "clarifying_questions": [],
        }
    )
    session = FakeSession(
        [
            FakeResponse(503, "Service Unavailable"),
            FakeResponse(502, "Bad Gateway"),
            FakeResponse(200, _make_completion_response(content)),
        ]
    )

    client = LLMClient(
        endpoint_url="https://api.openai.com",
        model="gpt-4o-mini",
        session=session,
    )
    with patch(
        "custom_components.automagic.llm_client._sleep_before_retry",
        AsyncMock(),
    ):
        result = await client.complete([{"role": "user", "content": "test"}])

    assert result["yaml"] == "alias: Test"
    assert len(session.post_calls) == 3


@pytest.mark.asyncio
async def test_complete_falls_back_without_response_format_when_provider_rejects_it():
    """Compatibility fallback should retry once without response_format."""
    content = json.dumps(
        {
            "yaml": "alias: Test",
            "summary": "A test automation",
            "needs_clarification": False,
            "clarifying_questions": [],
        }
    )
    session = FakeSession(
        [
            FakeResponse(400, '{"error":"response_format json_object not supported"}'),
            FakeResponse(200, _make_completion_response(content)),
        ]
    )

    client = LLMClient(
        endpoint_url="http://localhost:11434",
        model="llama3",
        session=session,
    )
    result = await client.complete([{"role": "user", "content": "test"}])

    assert result["yaml"] == "alias: Test"
    assert len(session.post_calls) == 2
    assert "response_format" in session.post_calls[0]["kwargs"]["json"]
    assert "response_format" not in session.post_calls[1]["kwargs"]["json"]


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
async def test_complete_salvages_loose_yaml_content():
    """Plain YAML responses should still be accepted when they contain a full automation."""
    raw = (
        "yaml\n"
        "yaml:\n"
        "alias: Victron Phase Imbalance Alert\n"
        "description: Warn on a phase imbalance.\n"
        "triggers:\n"
        "  - trigger: template\n"
        "actions:\n"
        "  - action: light.turn_on\n"
    )
    resp = FakeResponse(200, _make_completion_response(raw))
    session = FakeSession(resp)

    client = LLMClient(
        endpoint_url="http://localhost:11434",
        model="llama3",
        session=session,
    )
    result = await client.complete([{"role": "user", "content": "test"}])

    assert result["needs_clarification"] is False
    assert "alias: Victron Phase Imbalance Alert" in result["yaml"]
    assert "triggers:" in result["yaml"]
    assert "actions:" in result["yaml"]


@pytest.mark.asyncio
async def test_complete_salvages_loose_yaml_before_repairable_syntax_fixups():
    """Loose YAML should still parse before later repair when the model uses legacy section keys."""
    raw = (
        "yaml\n"
        "yaml:\n"
        "alias: Victron Phase Imbalance Alert\n"
        "description: Warn on a phase imbalance.\n"
        "trigger:\n"
        "  - platform: template\n"
        "action:\n"
        "  - service: light.turn_on\n"
    )
    resp = FakeResponse(200, _make_completion_response(raw))
    session = FakeSession(resp)

    client = LLMClient(
        endpoint_url="http://localhost:11434",
        model="llama3",
        session=session,
    )
    result = await client.complete([{"role": "user", "content": "test"}])

    assert result["needs_clarification"] is False
    assert "alias: Victron Phase Imbalance Alert" in result["yaml"]
    assert "trigger:" in result["yaml"]
    assert "action:" in result["yaml"]


@pytest.mark.asyncio
async def test_complete_normalizes_wrapped_yaml_string_inside_json_payload():
    """JSON payloads with a wrapped yaml string should be flattened before returning."""
    content = json.dumps(
        {
            "yaml": (
                "yaml\n"
                "yaml:\n"
                "alias: Victron Phase Imbalance Alert\n"
                "description: Warn on a phase imbalance.\n"
                "triggers:\n"
                "  - trigger: template\n"
                "actions:\n"
                "  - action: light.turn_on\n"
            ),
            "summary": "Ready to install",
            "needs_clarification": False,
            "clarifying_questions": [],
        }
    )
    resp = FakeResponse(200, _make_completion_response(content))
    session = FakeSession(resp)

    client = LLMClient(
        endpoint_url="http://localhost:11434",
        model="llama3",
        session=session,
    )
    result = await client.complete([{"role": "user", "content": "test"}])

    assert result["needs_clarification"] is False
    assert result["yaml"].startswith("alias: Victron Phase Imbalance Alert")
    assert not result["yaml"].startswith("yaml")


@pytest.mark.asyncio
async def test_complete_salvages_fenced_yaml_block_scalars_with_single_item_lists():
    """Fenced yaml: | responses should unwrap into a single automation mapping."""
    raw = (
        "```yaml\n"
        "yaml: |\n"
        "  - alias: Victron Phase Imbalance Alert\n"
        "    description: Warn on a phase imbalance.\n"
        "    trigger:\n"
        "      - platform: template\n"
        "    action:\n"
        "      - service: light.turn_on\n"
        "```"
    )
    resp = FakeResponse(200, _make_completion_response(raw))
    session = FakeSession(resp)

    client = LLMClient(
        endpoint_url="http://localhost:11434",
        model="llama3",
        session=session,
    )
    result = await client.complete([{"role": "user", "content": "test"}])

    assert result["needs_clarification"] is False
    assert result["yaml"].startswith("alias: Victron Phase Imbalance Alert")
    assert "\ntrigger:\n" in result["yaml"]
    assert "\naction:\n" in result["yaml"]


@pytest.mark.asyncio
async def test_complete_null_model_handled():
    """Test that null model field in response (LM Studio quirk) is handled."""
    content = json.dumps(
        {
            "yaml": "alias: Test",
            "summary": "test",
            "needs_clarification": False,
            "clarifying_questions": [],
        }
    )
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
async def test_complete_returns_clarification_payload():
    """Explicit clarification responses should stay interactive."""
    content = json.dumps(
        {
            "yaml": None,
            "summary": "I need to know which light should flash.",
            "needs_clarification": True,
            "clarifying_questions": ["Which light should flash?"],
        }
    )
    resp = FakeResponse(200, _make_completion_response(content))
    session = FakeSession(resp)

    client = LLMClient(
        endpoint_url="http://localhost:11434",
        model="llama3",
        session=session,
    )
    result = await client.complete([{"role": "user", "content": "test"}])

    assert result["yaml"] is None
    assert result["needs_clarification"] is True
    assert result["clarifying_questions"] == ["Which light should flash?"]


@pytest.mark.asyncio
async def test_complete_treats_question_only_summary_as_clarification():
    """Question-shaped summaries without YAML should not be marked complete."""
    content = json.dumps(
        {
            "yaml": None,
            "summary": "Which light should flash when the door opens?",
        }
    )
    resp = FakeResponse(200, _make_completion_response(content))
    session = FakeSession(resp)

    client = LLMClient(
        endpoint_url="http://localhost:11434",
        model="llama3",
        session=session,
    )
    result = await client.complete([{"role": "user", "content": "test"}])

    assert result["needs_clarification"] is True
    assert result["clarifying_questions"] == [
        "Which light should flash when the door opens?"
    ]


@pytest.mark.asyncio
async def test_from_config():
    """Test creating client from config dict."""
    config = {
        "endpoint_url": "http://localhost:1234",
        "model": "gpt-4o",
        "max_tokens": 4096,
        "request_timeout": 480,
        "temperature": 0.5,
        "api_key": "sk-test",
    }
    client = LLMClient.from_config(config)
    assert client._endpoint_url == "http://localhost:1234"
    assert client._model == "gpt-4o"
    assert client._max_tokens == 4096
    assert client._request_timeout == 480
    assert client._temperature == 0.5
    assert client._api_key == "sk-test"


def test_default_request_timeout_is_900_seconds():
    """Local clients should default to the longer generation timeout."""
    client = LLMClient(
        endpoint_url="http://localhost:11434",
        model="qwen2.5:3b-16k",
    )

    assert client._request_timeout == 900


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
async def test_fetch_models_openai_format_uses_bearer_token():
    """OpenAI model discovery should include the configured bearer token."""
    openai_resp = FakeResponse(
        200,
        {"data": [{"id": "gpt-4o-mini"}]},
    )
    session = FakeSession(openai_resp)

    models = await fetch_models(
        "https://api.openai.com",
        session=session,
        api_key="sk-openai",
    )

    assert models == ["gpt-4o-mini"]
    assert session.last_get["kwargs"]["headers"] == {
        "Authorization": "Bearer sk-openai"
    }


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
