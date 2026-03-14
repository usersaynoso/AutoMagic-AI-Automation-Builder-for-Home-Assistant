"""Tests for multi-service config normalization helpers."""

from __future__ import annotations

from custom_components.automagic.const import (
    CONF_API_KEY,
    CONF_DEFAULT_SERVICE_ID,
    CONF_ENDPOINT_URL,
    CONF_MODEL,
    CONF_PROVIDER,
    CONF_REQUEST_TIMEOUT,
    CONF_SERVICE_ID,
    CONF_SERVICES,
    PROVIDER_OPENAI,
)
from custom_components.automagic.service_config import (
    build_service_config,
    build_service_label,
    get_configured_services,
    get_service_config,
    normalize_config_data,
)


def test_normalize_config_data_migrates_legacy_single_service_shape():
    """Legacy config entries should be promoted into a service list."""
    legacy = {
        CONF_ENDPOINT_URL: "http://localhost:11434",
        CONF_MODEL: "qwen2.5:14b",
        CONF_REQUEST_TIMEOUT: 420,
    }

    normalized = normalize_config_data(legacy)

    assert normalized[CONF_MODEL] == "qwen2.5:14b"
    assert normalized[CONF_ENDPOINT_URL] == "http://localhost:11434"
    assert normalized[CONF_DEFAULT_SERVICE_ID]
    assert len(normalized[CONF_SERVICES]) == 1
    assert normalized[CONF_SERVICES][0][CONF_SERVICE_ID] == normalized[CONF_DEFAULT_SERVICE_ID]
    assert normalized[CONF_SERVICES][0][CONF_REQUEST_TIMEOUT] == 420


def test_get_service_config_returns_requested_service_or_default():
    """Requested service ids should win, otherwise the default service should be used."""
    primary = build_service_config(
        "http://localhost:11434",
        "qwen2.5:14b",
        service_id="primary",
        request_timeout=420,
    )
    backup = build_service_config(
        "http://remote:1234",
        "gpt-4o-mini",
        service_id="backup",
        request_timeout=900,
    )
    config = normalize_config_data(
        {
            CONF_SERVICES: [primary, backup],
            CONF_DEFAULT_SERVICE_ID: "backup",
        }
    )

    selected = get_service_config(config, "primary")
    default = get_service_config(config)
    services = get_configured_services(config)

    assert selected[CONF_SERVICE_ID] == "primary"
    assert default[CONF_SERVICE_ID] == "backup"
    assert [service[CONF_SERVICE_ID] for service in services] == ["primary", "backup"]


def test_build_service_label_uses_model_and_host():
    """Frontend labels should stay compact and readable."""
    service = build_service_config(
        "http://remote-host:1234",
        "gpt-4o-mini",
        service_id="cloud",
    )

    assert build_service_label(service) == "gpt-4o-mini (remote-host:1234)"


def test_openai_service_uses_fixed_endpoint_and_provider_label():
    """OpenAI-backed services should normalize to the hosted endpoint."""
    service = build_service_config(
        "",
        "gpt-4o-mini",
        service_id="openai",
        provider=PROVIDER_OPENAI,
        api_key="sk-test",
    )
    normalized = normalize_config_data(
        {
            CONF_SERVICES: [service],
            CONF_DEFAULT_SERVICE_ID: "openai",
        }
    )

    assert service[CONF_PROVIDER] == PROVIDER_OPENAI
    assert service[CONF_ENDPOINT_URL] == "https://api.openai.com"
    assert service[CONF_API_KEY] == "sk-test"
    assert build_service_label(service) == "OpenAI: gpt-4o-mini"
    assert normalized[CONF_PROVIDER] == PROVIDER_OPENAI
    assert normalized[CONF_API_KEY] == "sk-test"


def test_normalize_config_data_includes_service_subentries():
    """Runtime config should merge the primary service with subentry services."""
    primary = build_service_config(
        "http://localhost:11434",
        "qwen2.5:14b",
        service_id="primary",
    )
    subentry = {
        "data": build_service_config(
            "http://remote:1234",
            "gpt-4o-mini",
            service_id="backup",
        )
    }

    normalized = normalize_config_data(primary, [subentry])

    assert [service[CONF_SERVICE_ID] for service in normalized[CONF_SERVICES]] == [
        "primary",
        "backup",
    ]


def test_normalize_config_data_deduplicates_primary_service_subentry_mirror():
    """A visible primary-service subentry should not duplicate the runtime service list."""
    primary = build_service_config(
        "http://localhost:11434",
        "qwen2.5:14b",
        service_id="primary",
    )
    mirrored_primary = {
        "data": build_service_config(
            "http://localhost:11434",
            "qwen2.5:14b",
            service_id="primary",
        )
    }
    backup = {
        "data": build_service_config(
            "http://remote:1234",
            "gpt-4o-mini",
            service_id="backup",
        )
    }

    normalized = normalize_config_data(primary, [mirrored_primary, backup])

    assert [service[CONF_SERVICE_ID] for service in normalized[CONF_SERVICES]] == [
        "primary",
        "backup",
    ]
