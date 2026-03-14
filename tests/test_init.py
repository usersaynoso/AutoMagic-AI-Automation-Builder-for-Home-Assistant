"""Tests for integration setup and config-entry title handling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.automagic import async_setup_entry
from custom_components.automagic.service_config import build_service_config


@pytest.mark.asyncio
async def test_async_setup_entry_normalizes_existing_model_specific_titles():
    """Older entries should be retitled so subentries sit under AutoMagic, not a model."""
    hass = MagicMock()
    hass.data = {}
    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    hass.http.register_view = MagicMock()
    hass.config_entries = MagicMock()
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.title = "AutoMagic (qwen2.5:7b)"
    entry.data = build_service_config(
        "http://localhost:11434",
        "qwen2.5:7b",
        service_id="primary",
    )
    entry.subentries = {}
    entry.add_update_listener = MagicMock(return_value=MagicMock())
    entry.async_on_unload = MagicMock()

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
