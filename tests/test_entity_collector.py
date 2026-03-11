"""Tests for entity_collector module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.automagic.entity_collector import (
    get_entity_context,
    get_entity_summary_string,
)
from custom_components.automagic.const import PRIORITY_DOMAINS


def _make_entity_entry(
    entity_id: str,
    name: str | None = None,
    original_name: str | None = None,
    domain: str | None = None,
    device_class: str | None = None,
    original_device_class: str | None = None,
    disabled_by=None,
):
    """Create a mock entity registry entry."""
    entry = MagicMock()
    entry.entity_id = entity_id
    entry.name = name
    entry.original_name = original_name
    entry.domain = domain or entity_id.split(".")[0]
    entry.device_class = device_class
    entry.original_device_class = original_device_class
    entry.disabled_by = disabled_by
    return entry


def _make_state(entity_id: str, state: str, friendly_name: str | None = None, device_class: str | None = None):
    """Create a mock state object."""
    obj = MagicMock()
    obj.state = state
    obj.attributes = {}
    if friendly_name:
        obj.attributes["friendly_name"] = friendly_name
    if device_class:
        obj.attributes["device_class"] = device_class
    return obj


def _build_hass(entries, states_map):
    """Build a mock hass with entity registry and states."""
    hass = MagicMock()

    registry = MagicMock()
    registry.entities = MagicMock()
    registry.entities.values.return_value = entries

    hass.states.get = lambda eid: states_map.get(eid)

    return hass, registry


@pytest.mark.asyncio
async def test_basic_entity_collection():
    """Test that entities are collected and returned as dicts."""
    entries = [
        _make_entity_entry("light.living_room", name="Living Room Light"),
        _make_entity_entry("sensor.temperature", name="Temperature"),
    ]
    states = {
        "light.living_room": _make_state("light.living_room", "on"),
        "sensor.temperature": _make_state("sensor.temperature", "22.5"),
    }
    hass, registry = _build_hass(entries, states)

    with patch(
        "custom_components.automagic.entity_collector.er.async_get",
        return_value=registry,
    ):
        result = await get_entity_context(hass, max_entities=10)

    assert len(result) == 2
    assert result[0]["entity_id"] == "light.living_room"
    assert result[0]["name"] == "Living Room Light"
    assert result[0]["state"] == "on"
    assert result[0]["domain"] == "light"


@pytest.mark.asyncio
async def test_disabled_entities_are_excluded():
    """Test that disabled entities are skipped."""
    entries = [
        _make_entity_entry("light.active", name="Active"),
        _make_entity_entry("light.disabled", name="Disabled", disabled_by="user"),
    ]
    states = {
        "light.active": _make_state("light.active", "off"),
        "light.disabled": _make_state("light.disabled", "off"),
    }
    hass, registry = _build_hass(entries, states)

    with patch(
        "custom_components.automagic.entity_collector.er.async_get",
        return_value=registry,
    ):
        result = await get_entity_context(hass, max_entities=10)

    assert len(result) == 1
    assert result[0]["entity_id"] == "light.active"


@pytest.mark.asyncio
async def test_priority_domains_come_first():
    """Test that priority domains are sorted before non-priority ones."""
    entries = [
        _make_entity_entry("weather.home", name="Home Weather"),
        _make_entity_entry("light.lamp", name="Lamp"),
        _make_entity_entry("binary_sensor.door", name="Door"),
        _make_entity_entry("calendar.work", name="Work Calendar"),
    ]
    states = {
        "weather.home": _make_state("weather.home", "sunny"),
        "light.lamp": _make_state("light.lamp", "on"),
        "binary_sensor.door": _make_state("binary_sensor.door", "off"),
        "calendar.work": _make_state("calendar.work", "off"),
    }
    hass, registry = _build_hass(entries, states)

    with patch(
        "custom_components.automagic.entity_collector.er.async_get",
        return_value=registry,
    ):
        result = await get_entity_context(hass, max_entities=10)

    domains_in_order = [e["domain"] for e in result]
    # light and binary_sensor are priority; weather and calendar are not
    assert domains_in_order.index("light") < domains_in_order.index("weather")
    assert domains_in_order.index("binary_sensor") < domains_in_order.index("calendar")


@pytest.mark.asyncio
async def test_truncation_to_max_entities():
    """Test that results are truncated to max_entities."""
    entries = [
        _make_entity_entry(f"sensor.sensor_{i}", name=f"Sensor {i}")
        for i in range(100)
    ]
    states = {
        f"sensor.sensor_{i}": _make_state(f"sensor.sensor_{i}", str(i))
        for i in range(100)
    }
    hass, registry = _build_hass(entries, states)

    with patch(
        "custom_components.automagic.entity_collector.er.async_get",
        return_value=registry,
    ):
        result = await get_entity_context(hass, max_entities=15)

    assert len(result) == 15


@pytest.mark.asyncio
async def test_entity_summary_string_format():
    """Test the summary string output format."""
    entries = [
        _make_entity_entry("light.lamp", name="Lamp"),
        _make_entity_entry("switch.fan", name="Fan"),
    ]
    states = {
        "light.lamp": _make_state("light.lamp", "on"),
        "switch.fan": _make_state("switch.fan", "off"),
    }
    hass, registry = _build_hass(entries, states)

    with patch(
        "custom_components.automagic.entity_collector.er.async_get",
        return_value=registry,
    ):
        result = await get_entity_summary_string(hass, max_entities=10)

    assert "light.lamp (Lamp) [on]" in result
    assert "switch.fan (Fan) [off]" in result


@pytest.mark.asyncio
async def test_missing_state_returns_unknown():
    """Test that entities with no state object get 'unknown'."""
    entries = [
        _make_entity_entry("light.ghost", name="Ghost Light"),
    ]
    states = {}  # no state for this entity
    hass, registry = _build_hass(entries, states)

    with patch(
        "custom_components.automagic.entity_collector.er.async_get",
        return_value=registry,
    ):
        result = await get_entity_context(hass, max_entities=10)

    assert result[0]["state"] == "unknown"


@pytest.mark.asyncio
async def test_fallback_friendly_name():
    """Test name fallback chain: entry.name → original_name → attr → entity_id."""
    entries = [
        _make_entity_entry("sensor.no_name", name=None, original_name=None),
    ]
    states = {
        "sensor.no_name": _make_state("sensor.no_name", "42", friendly_name="Friendly Sensor"),
    }
    hass, registry = _build_hass(entries, states)

    with patch(
        "custom_components.automagic.entity_collector.er.async_get",
        return_value=registry,
    ):
        result = await get_entity_context(hass, max_entities=10)

    assert result[0]["name"] == "Friendly Sensor"
