"""AutoMagic - AI Automation Builder for Home Assistant."""

from __future__ import annotations

import logging
import os

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import AutoMagicEntitiesView, AutoMagicGenerateView, AutoMagicInstallView
from .const import DOMAIN

_CARD_URL = "/automagic/automagic-card.js"

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the AutoMagic integration (YAML config - not used)."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AutoMagic from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = dict(entry.data)

    # Serve the Lovelace card JS from the integration's own www/ directory.
    # This avoids requiring the user to manually copy files to config/www/.
    www_dir = os.path.join(os.path.dirname(__file__), "www")
    hass.http.register_static_path(_CARD_URL, os.path.join(www_dir, "automagic-card.js"), cache_headers=False)

    # Register API views
    hass.http.register_view(AutoMagicGenerateView())
    hass.http.register_view(AutoMagicInstallView())
    hass.http.register_view(AutoMagicEntitiesView())

    # Register the sidebar panel pointing to the integration-served JS
    hass.components.frontend.async_register_built_in_panel(
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
    )

    _LOGGER.info("AutoMagic integration loaded")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an AutoMagic config entry."""
    hass.data[DOMAIN].pop(entry.entry_id, None)

    # Remove the panel
    try:
        hass.components.frontend.async_remove_panel("automagic")
    except Exception:
        _LOGGER.debug("Panel 'automagic' was not registered or already removed")

    _LOGGER.info("AutoMagic integration unloaded")
    return True
