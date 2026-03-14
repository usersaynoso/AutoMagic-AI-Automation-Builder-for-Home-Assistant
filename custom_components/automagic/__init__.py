"""AutoMagic - AI Automation Builder for Home Assistant."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping

from homeassistant import config_entries
from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .api import (
    AutoMagicEntitiesView,
    AutoMagicGenerateView,
    AutoMagicGenerateStatusView,
    AutoMagicHistoryEntryView,
    AutoMagicHistoryView,
    AutoMagicInstallRepairView,
    AutoMagicInstallView,
    AutoMagicServicesView,
)
from .const import (
    CONF_API_KEY,
    CONF_DEFAULT_SERVICE_ID,
    CONF_ENDPOINT_URL,
    CONF_MODEL,
    CONF_PROVIDER,
    CONF_REQUEST_TIMEOUT,
    CONF_SERVICE_ID,
    DOMAIN,
    PROVIDER_OPENAI,
)
from .service_config import build_service_config, build_service_label, normalize_config_data
from .ws_api import async_register_websocket_commands

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_CARD_URL = "/automagic/automagic-card.js"
_DATA_STATIC_REGISTERED = "static_registered"
_DATA_VIEWS_REGISTERED = "views_registered"
_DATA_WS_REGISTERED = "ws_registered"
_SERVICE_SUBENTRY_TYPE = "service"

_LOGGER = logging.getLogger(__name__)


def _entry_title(data: dict) -> str:
    """Return the config-entry title for the current default service."""
    del data
    return "AutoMagic"


def _entry_runtime_config(entry: ConfigEntry) -> dict:
    """Return normalized entry data including any service subentries."""
    values = _entry_subentries(entry)
    return normalize_config_data(entry.data, values)


def _entry_subentries(entry: ConfigEntry) -> list:
    """Return config subentries as a list."""
    subentries = getattr(entry, "subentries", {})
    values = subentries.values() if hasattr(subentries, "values") else subentries
    return list(values or [])


def _primary_service_config(entry: ConfigEntry) -> dict | None:
    """Return the primary service config stored on the entry."""
    endpoint_url = str(entry.data.get(CONF_ENDPOINT_URL, "") or "").strip()
    model = str(entry.data.get(CONF_MODEL, "") or "").strip()
    provider = str(entry.data.get(CONF_PROVIDER, "") or "").strip().lower()
    api_key = str(entry.data.get(CONF_API_KEY, "") or "").strip()

    if not model:
        return None
    if provider != PROVIDER_OPENAI and not endpoint_url:
        return None

    return build_service_config(
        endpoint_url,
        model,
        service_id=entry.data.get(CONF_SERVICE_ID),
        provider=provider or None,
        api_key=api_key or None,
        max_tokens=entry.data.get("max_tokens"),
        request_timeout=entry.data.get(CONF_REQUEST_TIMEOUT),
        temperature=entry.data.get("temperature"),
    )


def _find_primary_service_subentry(entry: ConfigEntry, service_id: str):
    """Return the subentry that mirrors the primary service, if present."""
    normalized_service_id = str(service_id or "").strip()
    if not normalized_service_id:
        return None

    for subentry in _entry_subentries(entry):
        data = getattr(subentry, "data", None)
        if not isinstance(data, Mapping):
            continue
        if str(data.get(CONF_SERVICE_ID, "") or "").strip() == normalized_service_id:
            return subentry
    return None


def _sync_primary_service_subentry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Ensure the primary configured service also exists as a visible service subentry."""
    service = _primary_service_config(entry)
    if service is None:
        return

    title = build_service_label(service)
    existing = _find_primary_service_subentry(entry, service[CONF_SERVICE_ID])

    if existing is None:
        hass.config_entries.async_add_subentry(
            entry,
            config_entries.ConfigSubentry(
                data=service,
                subentry_type=_SERVICE_SUBENTRY_TYPE,
                title=title,
                unique_id=service[CONF_SERVICE_ID],
            ),
        )
        return

    hass.config_entries.async_update_subentry(
        entry,
        existing,
        data=service,
        title=title,
        unique_id=service[CONF_SERVICE_ID],
    )


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate legacy single-service entries to multi-service storage."""
    if entry.version >= 2:
        return True

    service = build_service_config(
        entry.data.get("endpoint_url", ""),
        entry.data.get("model", ""),
        service_id=entry.data.get("service_id"),
        provider=entry.data.get("provider"),
        api_key=entry.data.get("api_key"),
        max_tokens=entry.data.get("max_tokens"),
        request_timeout=entry.data.get("request_timeout"),
        temperature=entry.data.get("temperature"),
    )
    normalized = {
        **entry.data,
        **service,
        CONF_DEFAULT_SERVICE_ID: service["service_id"],
    }
    hass.config_entries.async_update_entry(
        entry,
        data=normalized,
        title=_entry_title(normalized),
        version=2,
    )
    _LOGGER.info("Migrated AutoMagic config entry %s to version 2", entry.entry_id)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AutoMagic from a config entry."""
    desired_title = _entry_title(entry.data)
    if entry.title != desired_title:
        hass.config_entries.async_update_entry(entry, title=desired_title)

    _sync_primary_service_subentry(hass, entry)

    domain_data = hass.data.setdefault(DOMAIN, {})
    domain_data[entry.entry_id] = _entry_runtime_config(entry)

    # Serve the Lovelace card JS from the integration's own www/ directory.
    # This avoids requiring the user to manually copy files to config/www/.
    if not domain_data.get(_DATA_STATIC_REGISTERED):
        www_dir = os.path.join(os.path.dirname(__file__), "www")
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    _CARD_URL,
                    os.path.join(www_dir, "automagic-card.js"),
                    cache_headers=False,
                )
            ]
        )
        domain_data[_DATA_STATIC_REGISTERED] = True

    # Register API views
    if not domain_data.get(_DATA_VIEWS_REGISTERED):
        hass.http.register_view(AutoMagicGenerateView())
        hass.http.register_view(AutoMagicGenerateStatusView())
        hass.http.register_view(AutoMagicInstallView())
        hass.http.register_view(AutoMagicInstallRepairView())
        hass.http.register_view(AutoMagicEntitiesView())
        hass.http.register_view(AutoMagicHistoryView())
        hass.http.register_view(AutoMagicHistoryEntryView())
        hass.http.register_view(AutoMagicServicesView())
        domain_data[_DATA_VIEWS_REGISTERED] = True

    if not domain_data.get(_DATA_WS_REGISTERED):
        async_register_websocket_commands(hass)
        domain_data[_DATA_WS_REGISTERED] = True

    # Make the card JS available as a Lovelace resource so users can add
    # custom:automagic-card to any dashboard without manual resource setup.
    frontend.add_extra_js_url(hass, _CARD_URL)

    # Register the sidebar panel pointing to the integration-served JS
    frontend.async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title="AutoMagic",
        sidebar_icon="mdi:robot",
        frontend_url_path="automagic",
        config={
            "_panel_custom": {
                "name": "automagic-card",
                "module_url": _CARD_URL,
            }
        },
        update=True,
    )

    # Refresh cached config when options change
    entry.async_on_unload(entry.add_update_listener(_update_listener))

    _LOGGER.info("AutoMagic integration loaded")
    return True


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Refresh cached config data when config entry is updated."""
    hass.data[DOMAIN][entry.entry_id] = _entry_runtime_config(entry)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an AutoMagic config entry."""
    domain_data = hass.data[DOMAIN]
    domain_data.pop(entry.entry_id, None)

    if not any(isinstance(value, dict) for value in domain_data.values()):
        frontend.async_remove_panel(hass, "automagic")
        domain_data.pop(_DATA_STATIC_REGISTERED, None)
        domain_data.pop(_DATA_VIEWS_REGISTERED, None)
        domain_data.pop(_DATA_WS_REGISTERED, None)

    _LOGGER.info("AutoMagic integration unloaded")
    return True
