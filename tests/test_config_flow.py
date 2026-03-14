"""Tests for OpenAI-specific config-flow helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.automagic.config_flow import (
    AutoMagicConfigFlow,
    AutoMagicServiceSubentryFlow,
    DEFAULT_OPENAI_MODEL,
    ENTRY_TITLE,
    LOCAL_LLM_SERVICE_LABEL,
    OPENAI_MODEL_OPTIONS,
    _async_fetch_openai_models,
    _async_resolve_openai_service,
    _entry_title,
)
from custom_components.automagic.const import (
    CONF_API_KEY,
    CONF_ENDPOINT_URL,
    CONF_MODEL,
    CONF_PROVIDER,
    CONF_REQUEST_TIMEOUT,
    CONF_SERVICE_ID,
    PROVIDER_OPENAI,
)
from custom_components.automagic.service_config import build_service_config


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


@pytest.mark.asyncio
async def test_async_resolve_openai_service_accepts_selected_supported_model():
    """Supported OpenAI dropdown values should be stored unchanged."""
    hass = MagicMock()

    with patch(
        "custom_components.automagic.config_flow._async_fetch_openai_models",
        AsyncMock(return_value=(["gpt-4o", "gpt-4o-mini"], None)),
    ):
        service, error = await _async_resolve_openai_service(
            hass,
            "sk-live",
            requested_model="gpt-4o",
        )

    assert error is None
    assert service[CONF_MODEL] == "gpt-4o"


@pytest.mark.asyncio
async def test_async_resolve_openai_service_rejects_unsupported_model():
    """Only the supported OpenAI dropdown values should be accepted."""
    hass = MagicMock()

    with patch(
        "custom_components.automagic.config_flow._async_fetch_openai_models",
        AsyncMock(return_value=(["gpt-4o", "gpt-4o-mini"], None)),
    ):
        service, error = await _async_resolve_openai_service(
            hass,
            "sk-live",
            requested_model="gpt-4.1",
        )

    assert service is None
    assert error == "unsupported_model"


def test_supported_subentry_types_expose_home_assistant_add_service_button():
    """The config flow should advertise service subentries to Home Assistant."""
    supported = AutoMagicConfigFlow.async_get_supported_subentry_types(MagicMock())

    assert supported == {"service": AutoMagicServiceSubentryFlow}


def test_config_flow_uses_native_subentry_management_without_options_flow():
    """The integration page should rely on subentries instead of a separate options flow."""
    assert "async_get_options_flow" not in AutoMagicConfigFlow.__dict__


def test_service_flow_labels_match_local_llm_and_supported_openai_models():
    """Config-flow constants should match the intended UI copy."""
    assert LOCAL_LLM_SERVICE_LABEL == "Local LLM"
    assert DEFAULT_OPENAI_MODEL == "gpt-4o-mini"
    assert tuple(OPENAI_MODEL_OPTIONS) == ("gpt-4o-mini", "gpt-4o")


def test_entry_title_stays_generic_when_multiple_services_exist():
    """The parent config entry should not look like one model owns the others."""
    assert _entry_title({CONF_MODEL: "qwen2.5:7b"}) == ENTRY_TITLE


def test_primary_config_entry_does_not_expose_reconfigure_flow():
    """The parent entry should not offer a separate reconfigure action."""
    assert "async_step_reconfigure" not in AutoMagicConfigFlow.__dict__
    assert "async_step_reconfigure" in AutoMagicServiceSubentryFlow.__dict__


@pytest.mark.asyncio
async def test_reconfigure_openai_subentry_preserves_existing_key_and_updates_title():
    """OpenAI subentries should allow model changes without re-entering the key."""
    flow = AutoMagicServiceSubentryFlow()
    flow.hass = MagicMock()
    flow.async_abort = MagicMock(
        return_value={"type": "abort", "reason": "reconfigure_successful"}
    )

    config_entry = MagicMock()
    config_entry.entry_id = "entry-1"
    config_subentry = MagicMock()
    config_subentry.data = build_service_config(
        "",
        "gpt-4o-mini",
        service_id="openai-service",
        provider=PROVIDER_OPENAI,
        api_key="sk-existing",
        request_timeout=480,
    )
    flow._get_entry = MagicMock(return_value=config_entry)
    flow._get_reconfigure_subentry = MagicMock(return_value=config_subentry)

    updated_service = build_service_config(
        "",
        "gpt-4o",
        service_id="openai-service",
        provider=PROVIDER_OPENAI,
        api_key="sk-existing",
        request_timeout=600,
    )

    with patch(
        "custom_components.automagic.config_flow._async_resolve_openai_service",
        AsyncMock(return_value=(updated_service, None)),
    ) as resolve_openai:
        result = await flow.async_step_reconfigure_openai(
            {
                CONF_API_KEY: "",
                CONF_MODEL: "gpt-4o",
                CONF_REQUEST_TIMEOUT: 600,
            }
        )

    assert result == {"type": "abort", "reason": "reconfigure_successful"}
    resolve_openai.assert_awaited_once()
    assert resolve_openai.await_args.kwargs["existing_api_key"] == "sk-existing"
    flow.hass.config_entries.async_update_subentry.assert_called_once()
    _, kwargs = flow.hass.config_entries.async_update_subentry.call_args
    assert kwargs["title"] == "OpenAI: gpt-4o"
    assert kwargs["data"][CONF_MODEL] == "gpt-4o"
    flow.hass.config_entries.async_schedule_reload.assert_called_once_with("entry-1")
