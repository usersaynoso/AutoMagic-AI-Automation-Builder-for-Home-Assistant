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
    CONF_DEFAULT_SERVICE_ID,
    CONF_ENDPOINT_URL,
    CONF_MODEL,
    CONF_REQUEST_TIMEOUT,
    CONF_SERVICE_ID,
    CONF_SERVICES,
    DEFAULT_ENDPOINT,
    DEFAULT_REQUEST_TIMEOUT,
    DOMAIN,
)
from .llm_client import fetch_models
from .service_config import (
    build_service_config,
    build_service_label,
    get_configured_services,
    get_default_service_id,
    get_model_max_tokens,
    get_model_temperature,
    get_service_config,
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


async def _async_resolve_service(
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


def _entry_title(config_data: dict[str, Any]) -> str:
    """Return the config-entry title."""
    service = get_service_config(config_data)
    model = service.get(CONF_MODEL, "") if service else ""
    return f"AutoMagic ({model})" if model else "AutoMagic"


def _service_choices(config_data: dict[str, Any]) -> dict[str, str]:
    """Return service id -> label mappings for options forms."""
    return {
        service[CONF_SERVICE_ID]: build_service_label(service)
        for service in get_configured_services(config_data)
    }


class AutoMagicConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for AutoMagic."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Single-step setup: connect one AI service, then add more in options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            service, error = await _async_resolve_service(
                self.hass,
                user_input[CONF_ENDPOINT_URL],
            )
            if service is not None:
                data = normalize_config_data(
                    {
                        CONF_SERVICES: [service],
                        CONF_DEFAULT_SERVICE_ID: service[CONF_SERVICE_ID],
                    }
                )

                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=_entry_title(data),
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


class AutoMagicOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for AutoMagic AI service management."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialise options flow."""
        self._config_entry = config_entry
        self._selected_service_id = ""

    def _current_config(self) -> dict[str, Any]:
        """Return normalized config-entry data."""
        return normalize_config_data(self._config_entry.data)

    def _update_entry(self, config_data: dict[str, Any]) -> FlowResult:
        """Persist updated config-entry data."""
        normalized = normalize_config_data(config_data)
        self.hass.config_entries.async_update_entry(
            self._config_entry,
            data=normalized,
            title=_entry_title(normalized),
        )
        return self.async_create_entry(title="", data={})

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Choose how to manage the configured AI services."""
        current = self._current_config()
        services = get_configured_services(current)
        action_options = {
            "add_service": "Add AI service",
            "edit_service": "Edit AI service",
        }
        if len(services) > 1:
            action_options["delete_service"] = "Delete AI service"
            action_options["default_service"] = "Choose default AI service"

        if user_input is not None:
            action = user_input.get("action")
            if action == "add_service":
                return await self.async_step_add_service()
            if action == "edit_service":
                return await self.async_step_edit_pick()
            if action == "delete_service":
                return await self.async_step_delete_service()
            if action == "default_service":
                return await self.async_step_default_service()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("action", default="add_service"): vol.In(
                        action_options
                    )
                }
            ),
        )

    async def async_step_add_service(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add a new AI service."""
        current = self._current_config()
        errors: dict[str, str] = {}

        if user_input is not None:
            service, error = await _async_resolve_service(
                self.hass,
                user_input[CONF_ENDPOINT_URL],
                user_input.get(CONF_MODEL, ""),
                user_input.get(CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT),
            )
            if service is not None:
                services = get_configured_services(current)
                services.append(service)
                return self._update_entry(
                    {
                        **current,
                        CONF_SERVICES: services,
                        CONF_DEFAULT_SERVICE_ID: get_default_service_id(current)
                        or service[CONF_SERVICE_ID],
                    }
                )
            if error:
                errors["base"] = error

        return self.async_show_form(
            step_id="add_service",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ENDPOINT_URL,
                        default=DEFAULT_ENDPOINT,
                    ): str,
                    vol.Optional(
                        CONF_MODEL,
                        default="",
                    ): str,
                    vol.Optional(
                        CONF_REQUEST_TIMEOUT,
                        default=DEFAULT_REQUEST_TIMEOUT,
                    ): vol.All(int, vol.Range(min=60, max=1800)),
                }
            ),
            errors=errors,
        )

    async def async_step_edit_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Choose which AI service to edit."""
        current = self._current_config()
        choices = _service_choices(current)
        if not choices:
            return self.async_abort(reason="service_not_found")

        if user_input is not None:
            self._selected_service_id = user_input[CONF_SERVICE_ID]
            return await self.async_step_edit_service()

        return self.async_show_form(
            step_id="edit_pick",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SERVICE_ID): vol.In(choices),
                }
            ),
        )

    async def async_step_edit_service(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit an existing AI service."""
        current = self._current_config()
        service = get_service_config(current, self._selected_service_id)
        if service is None:
            return self.async_abort(reason="service_not_found")

        errors: dict[str, str] = {}
        if user_input is not None:
            updated_service, error = await _async_resolve_service(
                self.hass,
                user_input[CONF_ENDPOINT_URL],
                user_input.get(CONF_MODEL, ""),
                user_input.get(
                    CONF_REQUEST_TIMEOUT,
                    service.get(CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT),
                ),
                service_id=service[CONF_SERVICE_ID],
            )
            if updated_service is not None:
                services = [
                    updated_service
                    if item.get(CONF_SERVICE_ID) == service[CONF_SERVICE_ID]
                    else item
                    for item in get_configured_services(current)
                ]
                return self._update_entry(
                    {
                        **current,
                        CONF_SERVICES: services,
                    }
                )
            if error:
                errors["base"] = error

        return self.async_show_form(
            step_id="edit_service",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ENDPOINT_URL,
                        default=service.get(CONF_ENDPOINT_URL, DEFAULT_ENDPOINT),
                    ): str,
                    vol.Optional(
                        CONF_MODEL,
                        default=service.get(CONF_MODEL, ""),
                    ): str,
                    vol.Optional(
                        CONF_REQUEST_TIMEOUT,
                        default=service.get(
                            CONF_REQUEST_TIMEOUT,
                            DEFAULT_REQUEST_TIMEOUT,
                        ),
                    ): vol.All(int, vol.Range(min=60, max=1800)),
                }
            ),
            errors=errors,
            description_placeholders={
                "service_name": build_service_label(service),
            },
        )

    async def async_step_delete_service(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Delete an AI service."""
        current = self._current_config()
        services = get_configured_services(current)
        if len(services) <= 1:
            return self.async_abort(reason="cannot_delete_last_service")

        choices = _service_choices(current)
        if user_input is not None:
            selected_id = user_input[CONF_SERVICE_ID]
            remaining_services = [
                service
                for service in services
                if service.get(CONF_SERVICE_ID) != selected_id
            ]
            default_service_id = get_default_service_id(current)
            if default_service_id == selected_id:
                default_service_id = remaining_services[0][CONF_SERVICE_ID]
            return self._update_entry(
                {
                    **current,
                    CONF_SERVICES: remaining_services,
                    CONF_DEFAULT_SERVICE_ID: default_service_id,
                }
            )

        return self.async_show_form(
            step_id="delete_service",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SERVICE_ID): vol.In(choices),
                }
            ),
        )

    async def async_step_default_service(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Choose the default AI service used by the panel."""
        current = self._current_config()
        services = get_configured_services(current)
        if len(services) <= 1:
            return self.async_create_entry(title="", data={})

        if user_input is not None:
            return self._update_entry(
                {
                    **current,
                    CONF_DEFAULT_SERVICE_ID: user_input[CONF_SERVICE_ID],
                }
            )

        return self.async_show_form(
            step_id="default_service",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SERVICE_ID,
                        default=get_default_service_id(current),
                    ): vol.In(_service_choices(current)),
                }
            ),
        )
