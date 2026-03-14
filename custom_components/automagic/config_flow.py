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

ENTRY_TITLE = "AutoMagic"
LOCAL_LLM_SERVICE_LABEL = "Local LLM"
OPENAI_MODEL_OPTIONS = {
    "gpt-4o-mini": "gpt-4o-mini",
    "gpt-4o": "gpt-4o",
}
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


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
    normalized_model = str(requested_model or "").strip() or DEFAULT_OPENAI_MODEL
    if normalized_model not in OPENAI_MODEL_OPTIONS:
        return None, "unsupported_model"

    normalized_api_key = str(api_key or "").strip() or str(existing_api_key or "").strip()

    _models, error = await _async_fetch_openai_models(hass, normalized_api_key)
    if error is not None:
        return None, error

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
    del config_data
    return ENTRY_TITLE


def _custom_service_schema(
    *,
    endpoint_url: str,
    model: str,
    request_timeout: int,
) -> vol.Schema:
    """Return the schema for a local/custom AI service."""
    return vol.Schema(
        {
            vol.Required(
                CONF_ENDPOINT_URL,
                default=endpoint_url,
            ): str,
            vol.Optional(CONF_MODEL, default=model): str,
            vol.Optional(
                CONF_REQUEST_TIMEOUT,
                default=request_timeout,
            ): vol.All(int, vol.Range(min=60, max=1800)),
        }
    )


def _openai_service_schema(
    *,
    api_key_required: bool,
    api_key: str,
    model: str,
    request_timeout: int,
) -> vol.Schema:
    """Return the schema for an OpenAI-backed AI service."""
    api_key_field = (
        vol.Required(CONF_API_KEY, default=api_key)
        if api_key_required
        else vol.Optional(CONF_API_KEY, default=api_key)
    )
    return vol.Schema(
        {
            api_key_field: str,
            vol.Required(
                CONF_MODEL,
                default=model,
            ): vol.In(OPENAI_MODEL_OPTIONS),
            vol.Optional(
                CONF_REQUEST_TIMEOUT,
                default=request_timeout,
            ): vol.All(int, vol.Range(min=60, max=1800)),
        }
    )


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

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Reconfigure the primary AI service."""
        config_entry = self._get_reconfigure_entry()
        provider = str(config_entry.data.get(CONF_PROVIDER, "") or "").strip().lower()
        if provider == PROVIDER_OPENAI:
            return await self.async_step_reconfigure_openai(user_input)
        return await self.async_step_reconfigure_local(user_input)

    async def async_step_reconfigure_local(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Reconfigure the primary local AI service."""
        errors: dict[str, str] = {}
        config_entry = self._get_reconfigure_entry()
        service_id = str(config_entry.data.get(CONF_SERVICE_ID, "") or "").strip() or None
        current_timeout = int(
            config_entry.data.get(CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT)
        )

        if user_input is not None:
            service, error = await _async_resolve_endpoint_service(
                self.hass,
                user_input[CONF_ENDPOINT_URL],
                user_input.get(CONF_MODEL, ""),
                user_input.get(CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT),
                service_id=service_id,
            )
            if service is not None:
                if _service_exists(
                    config_entry,
                    service,
                    ignore_service_id=service.get(CONF_SERVICE_ID, ""),
                ):
                    errors["base"] = "already_exists"
                else:
                    data = _persist_primary_service(
                        service,
                        config_entry.data,
                        default_service_id=get_default_service_id(
                            config_entry.data,
                            _entry_subentries(config_entry),
                        ),
                    )
                    return self.async_update_reload_and_abort(
                        config_entry,
                        data=data,
                        title=_entry_title(normalize_config_data(data)),
                    )
            elif error:
                errors["base"] = error

        return self.async_show_form(
            step_id="reconfigure_local",
            data_schema=_custom_service_schema(
                endpoint_url=str(
                    config_entry.data.get(CONF_ENDPOINT_URL, "") or DEFAULT_ENDPOINT
                ),
                model=str(config_entry.data.get(CONF_MODEL, "") or ""),
                request_timeout=current_timeout,
            ),
            errors=errors,
        )

    async def async_step_reconfigure_openai(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Reconfigure the primary OpenAI-backed AI service."""
        errors: dict[str, str] = {}
        config_entry = self._get_reconfigure_entry()
        service_id = str(config_entry.data.get(CONF_SERVICE_ID, "") or "").strip() or None
        current_timeout = int(
            config_entry.data.get(CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT)
        )
        current_api_key = str(config_entry.data.get(CONF_API_KEY, "") or "")

        if user_input is not None:
            service, error = await _async_resolve_openai_service(
                self.hass,
                user_input.get(CONF_API_KEY, ""),
                user_input.get(CONF_MODEL, ""),
                user_input.get(CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT),
                service_id=service_id,
                existing_api_key=current_api_key,
            )
            if service is not None:
                if _service_exists(
                    config_entry,
                    service,
                    ignore_service_id=service.get(CONF_SERVICE_ID, ""),
                ):
                    errors["base"] = "already_exists"
                else:
                    data = _persist_primary_service(
                        service,
                        config_entry.data,
                        default_service_id=get_default_service_id(
                            config_entry.data,
                            _entry_subentries(config_entry),
                        ),
                    )
                    return self.async_update_reload_and_abort(
                        config_entry,
                        data=data,
                        title=_entry_title(normalize_config_data(data)),
                    )
            elif error:
                errors["base"] = error

        return self.async_show_form(
            step_id="reconfigure_openai",
            data_schema=_openai_service_schema(
                api_key_required=False,
                api_key="",
                model=str(config_entry.data.get(CONF_MODEL, "") or DEFAULT_OPENAI_MODEL),
                request_timeout=current_timeout,
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_supported_subentry_types(
        config_entry: config_entries.ConfigEntry,
    ) -> dict[str, type[config_entries.ConfigSubentryFlow]]:
        """Return supported service subentry types."""
        return {"service": AutoMagicServiceSubentryFlow}


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
                            PROVIDER_CUSTOM: LOCAL_LLM_SERVICE_LABEL,
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
            data_schema=_custom_service_schema(
                endpoint_url=DEFAULT_ENDPOINT,
                model="",
                request_timeout=DEFAULT_REQUEST_TIMEOUT,
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
            data_schema=_openai_service_schema(
                api_key_required=True,
                api_key="",
                model=DEFAULT_OPENAI_MODEL,
                request_timeout=DEFAULT_REQUEST_TIMEOUT,
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Reconfigure an existing AI service subentry."""
        config_subentry = self._get_reconfigure_subentry()
        provider = str(config_subentry.data.get(CONF_PROVIDER, "") or "").strip().lower()
        if provider == PROVIDER_OPENAI:
            return await self.async_step_reconfigure_openai(user_input)
        return await self.async_step_reconfigure_local(user_input)

    async def async_step_reconfigure_local(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Reconfigure a local AI service subentry."""
        errors: dict[str, str] = {}
        config_entry = self._get_entry()
        config_subentry = self._get_reconfigure_subentry()
        service_id = str(config_subentry.data.get(CONF_SERVICE_ID, "") or "").strip() or None
        current_timeout = int(
            config_subentry.data.get(CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT)
        )

        if user_input is not None:
            service, error = await _async_resolve_endpoint_service(
                self.hass,
                user_input[CONF_ENDPOINT_URL],
                user_input.get(CONF_MODEL, ""),
                user_input.get(CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT),
                service_id=service_id,
            )
            if service is not None:
                if _service_exists(
                    config_entry,
                    service,
                    ignore_service_id=service.get(CONF_SERVICE_ID, ""),
                ):
                    errors["base"] = "already_exists"
                else:
                    self.hass.config_entries.async_update_subentry(
                        entry=config_entry,
                        subentry=config_subentry,
                        data=service,
                        title=build_service_label(service),
                    )
                    self.hass.config_entries.async_schedule_reload(config_entry.entry_id)
                    return self.async_abort(reason="reconfigure_successful")
            elif error:
                errors["base"] = error

        return self.async_show_form(
            step_id="reconfigure_local",
            data_schema=_custom_service_schema(
                endpoint_url=str(
                    config_subentry.data.get(CONF_ENDPOINT_URL, "") or DEFAULT_ENDPOINT
                ),
                model=str(config_subentry.data.get(CONF_MODEL, "") or ""),
                request_timeout=current_timeout,
            ),
            errors=errors,
        )

    async def async_step_reconfigure_openai(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Reconfigure an OpenAI AI service subentry."""
        errors: dict[str, str] = {}
        config_entry = self._get_entry()
        config_subentry = self._get_reconfigure_subentry()
        service_id = str(config_subentry.data.get(CONF_SERVICE_ID, "") or "").strip() or None
        current_timeout = int(
            config_subentry.data.get(CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT)
        )
        current_api_key = str(config_subentry.data.get(CONF_API_KEY, "") or "")

        if user_input is not None:
            service, error = await _async_resolve_openai_service(
                self.hass,
                user_input.get(CONF_API_KEY, ""),
                user_input.get(CONF_MODEL, ""),
                user_input.get(CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT),
                service_id=service_id,
                existing_api_key=current_api_key,
            )
            if service is not None:
                if _service_exists(
                    config_entry,
                    service,
                    ignore_service_id=service.get(CONF_SERVICE_ID, ""),
                ):
                    errors["base"] = "already_exists"
                else:
                    self.hass.config_entries.async_update_subentry(
                        entry=config_entry,
                        subentry=config_subentry,
                        data=service,
                        title=build_service_label(service),
                    )
                    self.hass.config_entries.async_schedule_reload(config_entry.entry_id)
                    return self.async_abort(reason="reconfigure_successful")
            elif error:
                errors["base"] = error

        return self.async_show_form(
            step_id="reconfigure_openai",
            data_schema=_openai_service_schema(
                api_key_required=False,
                api_key="",
                model=str(
                    config_subentry.data.get(CONF_MODEL, "") or DEFAULT_OPENAI_MODEL
                ),
                request_timeout=current_timeout,
            ),
            errors=errors,
        )
