"""Tests for multi-service config normalization helpers."""

from __future__ import annotations

from custom_components.automagic.const import (
    CONF_DEFAULT_SERVICE_ID,
    CONF_ENDPOINT_URL,
    CONF_MODEL,
    CONF_REQUEST_TIMEOUT,
    CONF_SERVICE_ID,
    CONF_SERVICES,
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
