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
    CONF_ENDPOINT_URL,
    CONF_MAX_TOKENS,
    CONF_MODEL,
    CONF_TEMPERATURE,
    DEFAULT_ENDPOINT,
    DEFAULT_LOCAL_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    DOMAIN,
    MODEL_MAX_TOKENS_MAP,
    MODEL_TEMPERATURE_MAP,
    PREFERRED_MODEL_ORDER,
)
from .llm_client import fetch_models

_LOGGER = logging.getLogger(__name__)


def _pick_default_model(models: list[str]) -> str:
    """Pick the best default model from a discovered model list."""
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


def _get_model_temperature(model: str) -> float:
    """Return the optimal temperature for a given model."""
    model_lower = model.lower()
    for prefix, temp in MODEL_TEMPERATURE_MAP.items():
        if model_lower.startswith(prefix):
            return temp
    return DEFAULT_TEMPERATURE


def _get_model_max_tokens(model: str) -> int:
    """Return the optimal max_tokens for a given model."""
    model_lower = model.lower()
    for prefix, tokens in MODEL_MAX_TOKENS_MAP.items():
        if model_lower.startswith(prefix):
            return tokens
    return DEFAULT_LOCAL_MAX_TOKENS


class AutoMagicConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for AutoMagic."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the config flow."""
        self._endpoint_url: str = DEFAULT_ENDPOINT
        self._models: list[str] = []
        self._detected_model: str = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Single-step setup: enter endpoint URL, everything else auto-detected."""
        errors: dict[str, str] = {}

        if user_input is not None:
            endpoint_url = user_input[CONF_ENDPOINT_URL].rstrip("/")
            self._endpoint_url = endpoint_url

            session = async_get_clientsession(self.hass)
            try:
                models = await fetch_models(endpoint_url, session=session)
            except Exception:
                models = []

            if models:
                self._models = models
                self._detected_model = _pick_default_model(models)

                model = self._detected_model or models[0]
                data = {
                    CONF_ENDPOINT_URL: endpoint_url,
                    CONF_MODEL: model,
                    CONF_TEMPERATURE: _get_model_temperature(model),
                    CONF_MAX_TOKENS: _get_model_max_tokens(model),
                }

                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"AutoMagic ({model})",
                    data=data,
                )

            # Endpoint reachable but no models? Let user enter manually
            import aiohttp

            try:
                async with session.get(
                    endpoint_url, timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    errors["base"] = "no_models"
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
        """Manage the options — endpoint URL and optional model override."""
        if user_input is not None:
            endpoint_url = user_input[CONF_ENDPOINT_URL].rstrip("/")
            model = user_input.get(CONF_MODEL, "").strip()

            # Re-fetch models if endpoint changed or no model specified
            if not model:
                session = async_get_clientsession(self.hass)
                try:
                    models = await fetch_models(endpoint_url, session=session)
                except Exception:
                    models = []
                model = _pick_default_model(models) or self._config_entry.data.get(CONF_MODEL, "")

            new_data = {
                CONF_ENDPOINT_URL: endpoint_url,
                CONF_MODEL: model,
                CONF_TEMPERATURE: _get_model_temperature(model),
                CONF_MAX_TOKENS: _get_model_max_tokens(model),
            }
            self.hass.config_entries.async_update_entry(
                self._config_entry,
                data=new_data,
                title=f"AutoMagic ({model})",
            )
            return self.async_create_entry(title="", data={})

        current = self._config_entry.data

        # Fetch available models for display
        endpoint_url = current.get(CONF_ENDPOINT_URL, DEFAULT_ENDPOINT)
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
                        CONF_ENDPOINT_URL,
                        default=current.get(CONF_ENDPOINT_URL, DEFAULT_ENDPOINT),
                    ): str,
                    vol.Optional(
                        CONF_MODEL,
                        default=current.get(CONF_MODEL, ""),
                    ): model_schema,
                }
            ),
        )
