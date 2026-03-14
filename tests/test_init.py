"""Tests for integration setup and config-entry title handling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.automagic import async_setup_entry
from custom_components.automagic.const import CONF_SERVICE_ID, CONF_SERVICES
from custom_components.automagic.service_config import build_service_config


def _build_hass_and_entry():
    """Create a minimal Home Assistant + config entry test harness."""
    hass = MagicMock()
    hass.data = {}
    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    hass.http.register_view = MagicMock()
    hass.config_entries = MagicMock()

    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = build_service_config(
        "http://localhost:11434",
        "qwen2.5:7b",
        service_id="primary",
    )
    entry.subentries = {}
    entry.add_update_listener = MagicMock(return_value=MagicMock())
    entry.async_on_unload = MagicMock()

    def add_subentry(config_entry, subentry):
        config_entry.subentries[subentry.subentry_id] = subentry
        return True

    def update_subentry(config_entry, subentry, **kwargs):
        if "data" in kwargs:
            subentry.data = kwargs["data"]
        if "title" in kwargs:
            subentry.title = kwargs["title"]
        if "unique_id" in kwargs:
            subentry.unique_id = kwargs["unique_id"]
        config_entry.subentries[subentry.subentry_id] = subentry
        return True

    hass.config_entries.async_add_subentry = MagicMock(side_effect=add_subentry)
    hass.config_entries.async_update_subentry = MagicMock(side_effect=update_subentry)
    hass.config_entries.async_update_entry = MagicMock()

    return hass, entry


@pytest.mark.asyncio
async def test_async_setup_entry_normalizes_existing_model_specific_titles():
    """Older entries should be retitled so subentries sit under AutoMagic, not a model."""
    hass, entry = _build_hass_and_entry()
    entry.title = "AutoMagic (qwen2.5:7b)"

    with patch(
        "custom_components.automagic.frontend.add_extra_js_url",
        MagicMock(),
    ), patch(
        "custom_components.automagic.frontend.async_register_built_in_panel",
        MagicMock(),
    ), patch(
        "custom_components.automagic.async_register_websocket_commands",
        MagicMock(),
    ):
        result = await async_setup_entry(hass, entry)

    assert result is True
    hass.config_entries.async_update_entry.assert_called_once_with(
        entry,
        title="AutoMagic",
    )


@pytest.mark.asyncio
async def test_async_setup_entry_creates_primary_service_subentry_when_missing():
    """The first configured service should appear alongside later service subentries."""
    hass, entry = _build_hass_and_entry()
    entry.title = "AutoMagic"

    with patch(
        "custom_components.automagic.frontend.add_extra_js_url",
        MagicMock(),
    ), patch(
        "custom_components.automagic.frontend.async_register_built_in_panel",
        MagicMock(),
    ), patch(
        "custom_components.automagic.async_register_websocket_commands",
        MagicMock(),
    ):
        result = await async_setup_entry(hass, entry)

    assert result is True
    hass.config_entries.async_add_subentry.assert_called_once()
    primary_subentry = next(iter(entry.subentries.values()))
    assert primary_subentry.title == "qwen2.5:7b (localhost:11434)"
    assert primary_subentry.data[CONF_SERVICE_ID] == "primary"
    assert [
        service[CONF_SERVICE_ID]
        for service in hass.data["automagic"]["entry-1"][CONF_SERVICES]
    ] == ["primary"]


@pytest.mark.asyncio
async def test_async_setup_entry_updates_existing_primary_service_subentry():
    """The visible primary-service row should stay in sync after reconfigure."""
    hass, entry = _build_hass_and_entry()
    entry.title = "AutoMagic"
    entry.subentries = {
        "primary-row": MagicMock(
            data=build_service_config(
                "http://localhost:11434",
                "qwen2.5:3b",
                service_id="primary",
            ),
            title="qwen2.5:3b (localhost:11434)",
            unique_id="primary",
            subentry_id="primary-row",
        )
    }
    entry.data = build_service_config(
        "http://localhost:11434",
        "qwen2.5:14b",
        service_id="primary",
    )

    with patch(
        "custom_components.automagic.frontend.add_extra_js_url",
        MagicMock(),
    ), patch(
        "custom_components.automagic.frontend.async_register_built_in_panel",
        MagicMock(),
    ), patch(
        "custom_components.automagic.async_register_websocket_commands",
        MagicMock(),
    ):
        result = await async_setup_entry(hass, entry)

    assert result is True
    hass.config_entries.async_add_subentry.assert_not_called()
    hass.config_entries.async_update_subentry.assert_called_once()
    _, kwargs = hass.config_entries.async_update_subentry.call_args
    assert kwargs["title"] == "qwen2.5:14b (localhost:11434)"
    assert kwargs["data"][CONF_SERVICE_ID] == "primary"
