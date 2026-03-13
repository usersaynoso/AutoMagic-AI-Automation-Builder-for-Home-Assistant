"""Tests for OpenAI-specific config-flow helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.automagic.config_flow import (
    AutoMagicConfigFlow,
    AutoMagicServiceSubentryFlow,
    _async_fetch_openai_models,
    _async_resolve_openai_service,
)
from custom_components.automagic.const import (
    CONF_API_KEY,
    CONF_ENDPOINT_URL,
    CONF_MODEL,
    CONF_PROVIDER,
    PROVIDER_OPENAI,
)


class FakeResponse:
    """Minimal aiohttp response stub for config-flow tests."""

    def __init__(self, status: int, body: dict):
        self.status = status
        self._body = body

    async def json(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


class FakeSession:
    """Minimal aiohttp session stub for config-flow tests."""

    def __init__(self, response: FakeResponse):
        self._response = response
        self.last_get = None

    def get(self, url, **kwargs):
        self.last_get = {"url": url, "kwargs": kwargs}
        return self._response


@pytest.mark.asyncio
async def test_async_fetch_openai_models_rejects_invalid_keys():
    """OpenAI helper should surface invalid-key errors explicitly."""
    hass = MagicMock()
    session = FakeSession(FakeResponse(401, {"error": {"message": "bad key"}}))

    with patch(
        "custom_components.automagic.config_flow.async_get_clientsession",
        return_value=session,
    ):
        models, error = await _async_fetch_openai_models(hass, "sk-bad")

    assert models == []
    assert error == "invalid_api_key"
    assert session.last_get["kwargs"]["headers"] == {
        "Authorization": "Bearer sk-bad"
    }


@pytest.mark.asyncio
async def test_async_resolve_openai_service_builds_openai_provider_config():
    """OpenAI helper should normalize to the fixed endpoint and provider."""
    hass = MagicMock()

    with patch(
        "custom_components.automagic.config_flow._async_fetch_openai_models",
        AsyncMock(return_value=(["gpt-4o", "gpt-4o-mini"], None)),
    ):
        service, error = await _async_resolve_openai_service(
            hass,
            "sk-live",
            request_timeout=480,
        )

    assert error is None
    assert service[CONF_PROVIDER] == PROVIDER_OPENAI
    assert service[CONF_API_KEY] == "sk-live"
    assert service[CONF_ENDPOINT_URL] == "https://api.openai.com"
    assert service[CONF_MODEL] == "gpt-4o-mini"


def test_supported_subentry_types_expose_home_assistant_add_service_button():
    """The config flow should advertise service subentries to Home Assistant."""
    supported = AutoMagicConfigFlow.async_get_supported_subentry_types(MagicMock())

    assert supported == {"service": AutoMagicServiceSubentryFlow}
