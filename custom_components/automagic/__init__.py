"""AutoMagic - AI Automation Builder for Home Assistant."""

from __future__ import annotations

import logging
import os

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .api import AutoMagicEntitiesView, AutoMagicGenerateView, AutoMagicInstallView
from .const import DOMAIN

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_CARD_URL = "/automagic/automagic-card.js"
_DATA_STATIC_REGISTERED = "static_registered"
_DATA_VIEWS_REGISTERED = "views_registered"

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AutoMagic from a config entry."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    domain_data[entry.entry_id] = dict(entry.data)

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
        hass.http.register_view(AutoMagicInstallView())
        hass.http.register_view(AutoMagicEntitiesView())
        domain_data[_DATA_VIEWS_REGISTERED] = True

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

    _LOGGER.info("AutoMagic integration loaded")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an AutoMagic config entry."""
    domain_data = hass.data[DOMAIN]
    domain_data.pop(entry.entry_id, None)

    if not any(isinstance(value, dict) for value in domain_data.values()):
        frontend.async_remove_panel(hass, "automagic", warn_if_unknown=False)

    _LOGGER.info("AutoMagic integration unloaded")
    return True
