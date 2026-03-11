"""Config flow for AutoMagic integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_CONTEXT_LIMIT,
    CONF_ENDPOINT_URL,
    CONF_MAX_TOKENS,
    CONF_MODEL,
    CONF_TEMPERATURE,
    DEFAULT_CONTEXT_LIMIT,
    DEFAULT_ENDPOINT,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    DOMAIN,
)
from .llm_client import fetch_models

_LOGGER = logging.getLogger(__name__)


class AutoMagicConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for AutoMagic."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the config flow."""
        self._endpoint_url: str = DEFAULT_ENDPOINT
        self._models: list[str] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: Connection - get LLM endpoint URL."""
        errors: dict[str, str] = {}

        if user_input is not None:
            endpoint_url = user_input[CONF_ENDPOINT_URL].rstrip("/")
            self._endpoint_url = endpoint_url

            # Try to fetch model list to verify connectivity
            session = async_get_clientsession(self.hass)
            try:
                models = await fetch_models(endpoint_url, session=session)
            except Exception:
                models = []

            if models:
                self._models = models
                return await self.async_step_model()

            # If no models returned, check if endpoint is reachable at all
            import aiohttp

            try:
                async with session.get(
                    endpoint_url, timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    # Endpoint is reachable but no models found - allow manual entry
                    self._models = []
                    return await self.async_step_model()
            except (aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ENDPOINT_URL, default=DEFAULT_ENDPOINT
                    ): str,
                }
            ),
            errors=errors,
        )

    async def async_step_model(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2: Model selection and parameters."""
        if user_input is not None:
            # Combine with endpoint from step 1
            data = {
                CONF_ENDPOINT_URL: self._endpoint_url,
                CONF_MODEL: user_input[CONF_MODEL],
                CONF_MAX_TOKENS: user_input.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS),
                CONF_TEMPERATURE: user_input.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE),
                CONF_CONTEXT_LIMIT: user_input.get(CONF_CONTEXT_LIMIT, DEFAULT_CONTEXT_LIMIT),
            }

            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"AutoMagic ({data[CONF_MODEL]})",
                data=data,
            )

        # Build model selector
        if self._models:
            model_schema = vol.In(self._models)
        else:
            model_schema = str

        return self.async_show_form(
            step_id="model",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MODEL): model_schema,
                    vol.Optional(
                        CONF_MAX_TOKENS, default=DEFAULT_MAX_TOKENS
                    ): vol.All(int, vol.Range(min=256, max=8192)),
                    vol.Optional(
                        CONF_TEMPERATURE, default=DEFAULT_TEMPERATURE
                    ): vol.All(float, vol.Range(min=0.0, max=1.0)),
                    vol.Optional(
                        CONF_CONTEXT_LIMIT, default=DEFAULT_CONTEXT_LIMIT
                    ): vol.All(int, vol.Range(min=1, max=500)),
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> AutoMagicOptionsFlow:
        """Return the options flow handler."""
        return AutoMagicOptionsFlow(config_entry)


class AutoMagicOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for AutoMagic (re-configure after setup)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialise options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self._config_entry.data
        endpoint_url = current.get(CONF_ENDPOINT_URL, DEFAULT_ENDPOINT)

        # Fetch models for the selector
        session = async_get_clientsession(self.hass)
        try:
            models = await fetch_models(endpoint_url, session=session)
        except Exception:
            models = []

        if models:
            model_schema = vol.In(models)
        else:
            model_schema = str

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MODEL,
                        default=current.get(CONF_MODEL, ""),
                    ): model_schema,
                    vol.Optional(
                        CONF_MAX_TOKENS,
                        default=current.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS),
                    ): vol.All(int, vol.Range(min=256, max=8192)),
                    vol.Optional(
                        CONF_TEMPERATURE,
                        default=current.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE),
                    ): vol.All(float, vol.Range(min=0.0, max=1.0)),
                    vol.Optional(
                        CONF_CONTEXT_LIMIT,
                        default=current.get(CONF_CONTEXT_LIMIT, DEFAULT_CONTEXT_LIMIT),
                    ): vol.All(int, vol.Range(min=1, max=500)),
                }
            ),
        )
