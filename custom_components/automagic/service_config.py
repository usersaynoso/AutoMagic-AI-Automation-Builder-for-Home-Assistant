"""Helpers for storing and selecting configured AI services."""

from __future__ import annotations

import uuid
from typing import Any, Mapping
from urllib.parse import urlparse

from .const import (
    CONF_API_KEY,
    CONF_DEFAULT_SERVICE_ID,
    CONF_ENDPOINT_URL,
    CONF_MAX_TOKENS,
    CONF_MODEL,
    CONF_PROVIDER,
    CONF_REQUEST_TIMEOUT,
    CONF_SERVICE_ID,
    CONF_SERVICES,
    CONF_TEMPERATURE,
    DEFAULT_LOCAL_MAX_TOKENS,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_TEMPERATURE,
    MODEL_MAX_TOKENS_MAP,
    MODEL_TEMPERATURE_MAP,
    OPENAI_ENDPOINT,
    PREFERRED_MODEL_ORDER,
    PROVIDER_CUSTOM,
    PROVIDER_OPENAI,
)


def pick_default_model(models: list[str]) -> str:
    """Pick the strongest preferred model from a discovered list."""
    if not models:
        return ""

    normalized = {model.lower(): model for model in models}

    for preferred in PREFERRED_MODEL_ORDER:
        if preferred in normalized:
            return normalized[preferred]

    for preferred in PREFERRED_MODEL_ORDER:
        for model in models:
            if model.lower().startswith(preferred):
                return model

    return models[0]


def get_model_temperature(model: str) -> float:
    """Return the recommended temperature for a model family."""
    model_lower = str(model or "").lower()
    for prefix, temperature in MODEL_TEMPERATURE_MAP.items():
        if model_lower.startswith(prefix):
            return temperature
    return DEFAULT_TEMPERATURE


def get_model_max_tokens(model: str) -> int:
    """Return the recommended max_tokens for a model family."""
    model_lower = str(model or "").lower()
    for prefix, max_tokens in MODEL_MAX_TOKENS_MAP.items():
        if model_lower.startswith(prefix):
            return max_tokens
    return DEFAULT_LOCAL_MAX_TOKENS


def _normalize_timeout(value: Any) -> int:
    """Return a safe timeout value for a configured service."""
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        timeout = DEFAULT_REQUEST_TIMEOUT
    return min(max(timeout, 60), 1800)


def _normalize_max_tokens(value: Any, model: str) -> int:
    """Return a safe max_tokens value for a configured service."""
    try:
        max_tokens = int(value)
    except (TypeError, ValueError):
        max_tokens = get_model_max_tokens(model)
    return max(1, max_tokens)


def _normalize_temperature(value: Any, model: str) -> float:
    """Return a safe temperature value for a configured service."""
    try:
        temperature = float(value)
    except (TypeError, ValueError):
        temperature = get_model_temperature(model)
    return max(0.0, min(temperature, 2.0))


def _normalize_provider(provider: Any, endpoint_url: str, api_key: str) -> str:
    """Return the normalized provider name for a service."""
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider in {PROVIDER_CUSTOM, PROVIDER_OPENAI}:
        return normalized_provider

    parsed = urlparse(endpoint_url)
    hostname = (parsed.hostname or "").lower()
    if api_key and hostname == "api.openai.com":
        return PROVIDER_OPENAI
    return PROVIDER_CUSTOM


def build_service_config(
    endpoint_url: str,
    model: str,
    *,
    service_id: str | None = None,
    provider: str | None = None,
    api_key: str | None = None,
    max_tokens: int | None = None,
    request_timeout: int | None = None,
    temperature: float | None = None,
) -> dict[str, Any]:
    """Build a normalized AI service configuration."""
    normalized_model = str(model or "").strip()
    normalized_api_key = str(api_key or "").strip()
    candidate_endpoint = str(endpoint_url or "").strip().rstrip("/")
    normalized_provider = _normalize_provider(
        provider,
        candidate_endpoint,
        normalized_api_key,
    )
    normalized_endpoint = (
        OPENAI_ENDPOINT if normalized_provider == PROVIDER_OPENAI else candidate_endpoint
    )
    resolved_service_id = str(service_id or "").strip() or uuid.uuid4().hex

    return {
        CONF_SERVICE_ID: resolved_service_id,
        CONF_PROVIDER: normalized_provider,
        CONF_API_KEY: normalized_api_key,
        CONF_ENDPOINT_URL: normalized_endpoint,
        CONF_MODEL: normalized_model,
        CONF_MAX_TOKENS: _normalize_max_tokens(max_tokens, normalized_model),
        CONF_REQUEST_TIMEOUT: _normalize_timeout(request_timeout),
        CONF_TEMPERATURE: _normalize_temperature(temperature, normalized_model),
    }


def build_service_label(service: Mapping[str, Any]) -> str:
    """Return a human-readable label for a configured AI service."""
    provider = str(service.get(CONF_PROVIDER, "") or "").strip().lower()
    model = str(service.get(CONF_MODEL, "") or "").strip()
    if provider == PROVIDER_OPENAI:
        return f"OpenAI: {model}" if model else "OpenAI"

    endpoint = str(service.get(CONF_ENDPOINT_URL, "") or "").strip()
    parsed = urlparse(endpoint)
    endpoint_label = parsed.netloc or parsed.path or endpoint

    if model and endpoint_label:
        return f"{model} ({endpoint_label})"
    if model:
        return model
    if endpoint_label:
        return endpoint_label
    return "AI service"


def normalize_config_data(data: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize config-entry data into the multi-service storage shape."""
    normalized: dict[str, Any] = dict(data or {})

    raw_services = normalized.get(CONF_SERVICES)
    services: list[dict[str, Any]] = []

    if isinstance(raw_services, list):
        for raw_service in raw_services:
            if not isinstance(raw_service, Mapping):
                continue
            endpoint_url = str(raw_service.get(CONF_ENDPOINT_URL, "") or "").strip()
            model = str(raw_service.get(CONF_MODEL, "") or "").strip()
            provider = str(raw_service.get(CONF_PROVIDER, "") or "").strip().lower()
            api_key = str(raw_service.get(CONF_API_KEY, "") or "").strip()
            if not model:
                continue
            if provider != PROVIDER_OPENAI and not endpoint_url:
                continue
            services.append(
                build_service_config(
                    endpoint_url,
                    model,
                    service_id=str(raw_service.get(CONF_SERVICE_ID, "") or "").strip() or None,
                    provider=provider or None,
                    api_key=api_key or None,
                    max_tokens=raw_service.get(CONF_MAX_TOKENS),
                    request_timeout=raw_service.get(CONF_REQUEST_TIMEOUT),
                    temperature=raw_service.get(CONF_TEMPERATURE),
                )
            )

    if not services:
        endpoint_url = str(normalized.get(CONF_ENDPOINT_URL, "") or "").strip()
        model = str(normalized.get(CONF_MODEL, "") or "").strip()
        provider = str(normalized.get(CONF_PROVIDER, "") or "").strip().lower()
        api_key = str(normalized.get(CONF_API_KEY, "") or "").strip()
        if model and (endpoint_url or provider == PROVIDER_OPENAI):
            services.append(
                build_service_config(
                    endpoint_url,
                    model,
                    service_id=str(normalized.get(CONF_SERVICE_ID, "") or "").strip() or None,
                    provider=provider or None,
                    api_key=api_key or None,
                    max_tokens=normalized.get(CONF_MAX_TOKENS),
                    request_timeout=normalized.get(CONF_REQUEST_TIMEOUT),
                    temperature=normalized.get(CONF_TEMPERATURE),
                )
            )

    default_service_id = str(normalized.get(CONF_DEFAULT_SERVICE_ID, "") or "").strip()
    if not any(service[CONF_SERVICE_ID] == default_service_id for service in services):
        default_service_id = services[0][CONF_SERVICE_ID] if services else ""

    normalized[CONF_SERVICES] = services
    normalized[CONF_DEFAULT_SERVICE_ID] = default_service_id
    normalized[CONF_SERVICE_ID] = default_service_id

    default_service = next(
        (
            service
            for service in services
            if service[CONF_SERVICE_ID] == default_service_id
        ),
        services[0] if services else None,
    )

    if default_service is not None:
        normalized[CONF_PROVIDER] = default_service[CONF_PROVIDER]
        normalized[CONF_API_KEY] = default_service[CONF_API_KEY]
        normalized[CONF_ENDPOINT_URL] = default_service[CONF_ENDPOINT_URL]
        normalized[CONF_MODEL] = default_service[CONF_MODEL]
        normalized[CONF_MAX_TOKENS] = default_service[CONF_MAX_TOKENS]
        normalized[CONF_REQUEST_TIMEOUT] = default_service[CONF_REQUEST_TIMEOUT]
        normalized[CONF_TEMPERATURE] = default_service[CONF_TEMPERATURE]

    return normalized


def get_configured_services(
    config_data: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Return all configured AI services."""
    normalized = normalize_config_data(config_data)
    return [dict(service) for service in normalized.get(CONF_SERVICES, [])]


def get_default_service_id(config_data: Mapping[str, Any] | None) -> str:
    """Return the configured default service id."""
    normalized = normalize_config_data(config_data)
    return str(normalized.get(CONF_DEFAULT_SERVICE_ID, "") or "")


def get_service_config(
    config_data: Mapping[str, Any] | None,
    service_id: str | None = None,
) -> dict[str, Any] | None:
    """Return the requested service config or the default service."""
    normalized = normalize_config_data(config_data)
    services = normalized.get(CONF_SERVICES, [])
    if not services:
        return None

    requested_id = str(service_id or "").strip()
    if requested_id:
        for service in services:
            if service.get(CONF_SERVICE_ID) == requested_id:
                return dict(service)

    default_service_id = str(normalized.get(CONF_DEFAULT_SERVICE_ID, "") or "")
    for service in services:
        if service.get(CONF_SERVICE_ID) == default_service_id:
            return dict(service)

    return dict(services[0])
