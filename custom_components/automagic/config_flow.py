"""Config flow for AutoMagic integration."""

from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_API_KEY,
    CONF_DEFAULT_SERVICE_ID,
    CONF_ENDPOINT_URL,
    CONF_MODEL,
    CONF_PROVIDER,
    CONF_REQUEST_TIMEOUT,
    CONF_SERVICE_ID,
    DEFAULT_ENDPOINT,
    DEFAULT_REQUEST_TIMEOUT,
    DOMAIN,
    OPENAI_ENDPOINT,
    PROVIDER_CUSTOM,
    PROVIDER_OPENAI,
)
from .llm_client import fetch_models
from .service_config import (
    build_service_config,
    build_service_label,
    get_configured_services,
    get_default_service_id,
    get_model_max_tokens,
    get_model_temperature,
    normalize_config_data,
    pick_default_model,
)


def _pick_default_model(models: list[str]) -> str:
    """Pick the best default model from a discovered model list."""
    return pick_default_model(models)


def _get_model_temperature(model: str) -> float:
    """Return the optimal temperature for a given model."""
    return get_model_temperature(model)


def _get_model_max_tokens(model: str) -> int:
    """Return the optimal max_tokens for a given model."""
    return get_model_max_tokens(model)


def _entry_subentries(config_entry: config_entries.ConfigEntry) -> list[Any]:
    """Return config subentries as a list."""
    subentries = getattr(config_entry, "subentries", {})
    if hasattr(subentries, "values"):
        return list(subentries.values())
    if isinstance(subentries, list):
        return subentries
    return []


def _persist_primary_service(
    service: dict[str, Any],
    existing_data: dict[str, Any] | None = None,
    *,
    default_service_id: str | None = None,
) -> dict[str, Any]:
    """Persist the primary service on the config entry without runtime mirrors."""
    persisted = dict(existing_data or {})
    persisted.update(service)
    persisted[CONF_DEFAULT_SERVICE_ID] = (
        str(default_service_id or "").strip() or service[CONF_SERVICE_ID]
    )
    return persisted


def _runtime_config(config_entry: config_entries.ConfigEntry) -> dict[str, Any]:
    """Return normalized runtime config including service subentries."""
    return normalize_config_data(config_entry.data, _entry_subentries(config_entry))


def _service_exists(
    config_entry: config_entries.ConfigEntry,
    candidate: dict[str, Any],
    *,
    ignore_service_id: str = "",
) -> bool:
    """Return whether the candidate duplicates an existing configured service."""
    ignore_id = str(ignore_service_id or "").strip()
    for service in get_configured_services(
        config_entry.data, _entry_subentries(config_entry)
    ):
        service_id = str(service.get(CONF_SERVICE_ID, "") or "").strip()
        if ignore_id and service_id == ignore_id:
            continue
        if (
            str(service.get(CONF_PROVIDER, "") or "").strip().lower()
            == str(candidate.get(CONF_PROVIDER, "") or "").strip().lower()
            and str(service.get(CONF_ENDPOINT_URL, "") or "").strip()
            == str(candidate.get(CONF_ENDPOINT_URL, "") or "").strip()
            and str(service.get(CONF_MODEL, "") or "").strip()
            == str(candidate.get(CONF_MODEL, "") or "").strip()
        ):
            return True
    return False


async def _async_endpoint_is_reachable(hass, endpoint_url: str) -> bool:
    """Return whether the endpoint answers a basic HTTP request."""
    session = async_get_clientsession(hass)
    try:
        async with session.get(
            endpoint_url.rstrip("/"),
            timeout=aiohttp.ClientTimeout(total=5),
        ):
            return True
    except (aiohttp.ClientError, TimeoutError):
        return False


async def _async_fetch_openai_models(
    hass, api_key: str
) -> tuple[list[str], str | None]:
    """Fetch available OpenAI models with explicit API-key validation."""
    normalized_api_key = str(api_key or "").strip()
    if not normalized_api_key:
        return [], "missing_api_key"

    session = async_get_clientsession(hass)
    try:
        async with session.get(
            f"{OPENAI_ENDPOINT}/v1/models",
            timeout=aiohttp.ClientTimeout(total=10),
            headers={"Authorization": f"Bearer {normalized_api_key}"},
        ) as resp:
            if resp.status in {401, 403}:
                return [], "invalid_api_key"
            if resp.status != 200:
                return [], "cannot_connect"
            data = await resp.json()
    except (aiohttp.ClientError, TimeoutError, ValueError):
        return [], "cannot_connect"

    models = [
        model["id"]
        for model in data.get("data", [])
        if isinstance(model, dict) and model.get("id")
    ]
    return sorted(models), None


async def _async_resolve_endpoint_service(
    hass,
    endpoint_url: str,
    requested_model: str = "",
    request_timeout: int = DEFAULT_REQUEST_TIMEOUT,
    service_id: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Validate an endpoint/model pair and return normalized service data."""
    normalized_endpoint = str(endpoint_url or "").strip().rstrip("/")
    normalized_model = str(requested_model or "").strip()

    session = async_get_clientsession(hass)
    try:
        models = await fetch_models(normalized_endpoint, session=session)
    except Exception:
        models = []

    if models and not normalized_model:
        normalized_model = _pick_default_model(models) or models[0]

    if not normalized_model:
        if await _async_endpoint_is_reachable(hass, normalized_endpoint):
            return None, "no_models"
        return None, "cannot_connect"

    if not models and not await _async_endpoint_is_reachable(hass, normalized_endpoint):
        return None, "cannot_connect"

    return (
        build_service_config(
            normalized_endpoint,
            normalized_model,
            service_id=service_id,
            request_timeout=request_timeout,
        ),
        None,
    )


async def _async_resolve_openai_service(
    hass,
    api_key: str,
    requested_model: str = "",
    request_timeout: int = DEFAULT_REQUEST_TIMEOUT,
    service_id: str | None = None,
    existing_api_key: str = "",
) -> tuple[dict[str, Any] | None, str | None]:
    """Validate an OpenAI API key/model pair and return service data."""
    normalized_model = str(requested_model or "").strip()
    normalized_api_key = str(api_key or "").strip() or str(existing_api_key or "").strip()

    models, error = await _async_fetch_openai_models(hass, normalized_api_key)
    if error is not None:
        return None, error

    if models and not normalized_model:
        normalized_model = _pick_default_model(models) or models[0]

    if not normalized_model:
        return None, "no_models"

    return (
        build_service_config(
            OPENAI_ENDPOINT,
            normalized_model,
            service_id=service_id,
            provider=PROVIDER_OPENAI,
            api_key=normalized_api_key,
            request_timeout=request_timeout,
        ),
        None,
    )


def _entry_title(config_data: dict[str, Any]) -> str:
    """Return the config-entry title."""
    services = get_configured_services(config_data)
    default_service_id = get_default_service_id(config_data)
    service = next(
        (
            item
            for item in services
            if item.get(CONF_SERVICE_ID) == default_service_id
        ),
        services[0] if services else None,
    )
    model = service.get(CONF_MODEL, "") if service else ""
    return f"AutoMagic ({model})" if model else "AutoMagic"


class AutoMagicConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for AutoMagic."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Single-step setup: connect one AI service."""
        errors: dict[str, str] = {}

        if user_input is not None:
            service, error = await _async_resolve_endpoint_service(
                self.hass,
                user_input[CONF_ENDPOINT_URL],
            )
            if service is not None:
                data = _persist_primary_service(service)

                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=_entry_title(normalize_config_data(data)),
                    data=data,
                )

            if error:
                errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ENDPOINT_URL,
                        default=DEFAULT_ENDPOINT,
                    ): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> AutoMagicOptionsFlow:
        """Return the options flow handler."""
        return AutoMagicOptionsFlow(config_entry)

    @staticmethod
    @callback
    def async_get_supported_subentry_types(
        config_entry: config_entries.ConfigEntry,
    ) -> dict[str, type[config_entries.ConfigSubentryFlow]]:
        """Return supported service subentry types."""
        return {"service": AutoMagicServiceSubentryFlow}


class AutoMagicOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for default service selection."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialise options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Choose the default AI service used by the panel."""
        current = _runtime_config(self._config_entry)
        services = get_configured_services(current)
        if len(services) <= 1:
            return self.async_abort(reason="single_service")

        if user_input is not None:
            new_data = {
                **self._config_entry.data,
                CONF_DEFAULT_SERVICE_ID: user_input[CONF_SERVICE_ID],
            }
            self.hass.config_entries.async_update_entry(
                self._config_entry,
                data=new_data,
                title=_entry_title(
                    normalize_config_data(new_data, _entry_subentries(self._config_entry))
                ),
            )
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SERVICE_ID,
                        default=get_default_service_id(current),
                    ): vol.In(
                        {
                            service[CONF_SERVICE_ID]: build_service_label(service)
                            for service in services
                        }
                    ),
                }
            ),
        )


class AutoMagicServiceSubentryFlow(config_entries.ConfigSubentryFlow):
    """Add extra AutoMagic services using Home Assistant subentries."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Choose the type of service to add."""
        if user_input is not None:
            service_type = user_input.get("service_type")
            if service_type == PROVIDER_OPENAI:
                return await self.async_step_openai_service()
            return await self.async_step_custom_service()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("service_type", default=PROVIDER_CUSTOM): vol.In(
                        {
                            PROVIDER_CUSTOM: "Compatible endpoint",
                            PROVIDER_OPENAI: "OpenAI API key",
                        }
                    )
                }
            ),
        )

    async def async_step_custom_service(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add a URL-based AI service."""
        errors: dict[str, str] = {}
        config_entry = self._get_entry()

        if user_input is not None:
            service, error = await _async_resolve_endpoint_service(
                self.hass,
                user_input[CONF_ENDPOINT_URL],
                user_input.get(CONF_MODEL, ""),
                user_input.get(CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT),
            )
            if service is not None:
                if _service_exists(config_entry, service):
                    errors["base"] = "already_exists"
                else:
                    return self.async_create_entry(
                        title=build_service_label(service),
                        data=service,
                    )
            elif error:
                errors["base"] = error

        return self.async_show_form(
            step_id="custom_service",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ENDPOINT_URL,
                        default=DEFAULT_ENDPOINT,
                    ): str,
                    vol.Optional(CONF_MODEL, default=""): str,
                    vol.Optional(
                        CONF_REQUEST_TIMEOUT,
                        default=DEFAULT_REQUEST_TIMEOUT,
                    ): vol.All(int, vol.Range(min=60, max=1800)),
                }
            ),
            errors=errors,
        )

    async def async_step_openai_service(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add an OpenAI-backed AI service."""
        errors: dict[str, str] = {}
        config_entry = self._get_entry()

        if user_input is not None:
            service, error = await _async_resolve_openai_service(
                self.hass,
                user_input.get(CONF_API_KEY, ""),
                user_input.get(CONF_MODEL, ""),
                user_input.get(CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT),
            )
            if service is not None:
                if _service_exists(config_entry, service):
                    errors["base"] = "already_exists"
                else:
                    return self.async_create_entry(
                        title=build_service_label(service),
                        data=service,
                    )
            elif error:
                errors["base"] = error

        return self.async_show_form(
            step_id="openai_service",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): str,
                    vol.Optional(CONF_MODEL, default=""): str,
                    vol.Optional(
                        CONF_REQUEST_TIMEOUT,
                        default=DEFAULT_REQUEST_TIMEOUT,
                    ): vol.All(int, vol.Range(min=60, max=1800)),
                }
            ),
            errors=errors,
        )
