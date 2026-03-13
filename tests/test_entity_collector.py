"""Tests for entity_collector module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.automagic.entity_collector import (
    _relevant_domain_matches,
    get_entity_context,
    get_entity_summary_string,
    select_relevant_entities,
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


def _build_hass(entries, states_map, services_map=None):
    """Build a mock hass with entity registry and states."""
    hass = MagicMock()

    registry = MagicMock()
    registry.entities = MagicMock()
    registry.entities.values.return_value = entries

    hass.states.get = lambda eid: states_map.get(eid)
    hass.services.async_services.return_value = services_map or {}

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
async def test_notification_services_are_exposed_as_prompt_targets():
    """Notify services should be surfaced so the LLM can choose a real target."""
    entries = [
        _make_entity_entry("light.lounge_lamp", name="Lounge Lamp"),
    ]
    states = {
        "light.lounge_lamp": _make_state("light.lounge_lamp", "off"),
    }
    services = {
        "notify": {
            "mobile_app_iphone_13": {},
            "notify": {},
        }
    }
    hass, registry = _build_hass(entries, states, services_map=services)

    with patch(
        "custom_components.automagic.entity_collector.er.async_get",
        return_value=registry,
    ):
        result = await get_entity_context(hass, max_entities=10)

    entity_ids = [entity["entity_id"] for entity in result]
    assert "notify.mobile_app_iphone_13" in entity_ids
    notify_entry = next(
        entity for entity in result if entity["entity_id"] == "notify.mobile_app_iphone_13"
    )
    assert notify_entry["domain"] == "notify"
    assert notify_entry["state"] == "service"
    assert notify_entry["name"] == "Notify Iphone 13"


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


def test_select_relevant_entities_prefers_prompt_matches():
    """Prompt terms should pull matching entities to the front of the shortlist."""
    entities = [
        {"entity_id": "light.office", "name": "Office Light", "domain": "light", "state": "off", "device_class": None},
        {"entity_id": "light.kitchen", "name": "Kitchen Light", "domain": "light", "state": "off", "device_class": None},
        {"entity_id": "binary_sensor.front_door", "name": "Front Door", "domain": "binary_sensor", "state": "off", "device_class": "door"},
        {"entity_id": "sensor.outdoor_temp", "name": "Outdoor Temperature", "domain": "sensor", "state": "12", "device_class": "temperature"},
    ]

    result = select_relevant_entities(
        "Turn on the kitchen light when the front door opens",
        entities,
        max_entities=3,
        fallback_entities=1,
    )

    entity_ids = [entity["entity_id"] for entity in result]
    assert "light.kitchen" in entity_ids
    assert "binary_sensor.front_door" in entity_ids


def test_select_relevant_entities_keeps_useful_short_tokens():
    """Useful short tokens like AC should still help rank matching entities."""
    entities = [
        {
            "entity_id": "sensor.victron_mk3_ac_output_power",
            "name": "AC Output Power",
            "domain": "sensor",
            "state": "1234",
            "device_class": "power",
        },
        {
            "entity_id": "sensor.grid_output_power",
            "name": "Grid Output Power",
            "domain": "sensor",
            "state": "200",
            "device_class": "power",
        },
        {
            "entity_id": "light.lounge_lamp",
            "name": "Lounge Lamp",
            "domain": "light",
            "state": "off",
            "device_class": None,
        },
    ]

    result = select_relevant_entities(
        "Alert me if AC output power goes above 3000w",
        entities,
        max_entities=2,
        fallback_entities=0,
    )

    assert result[0]["entity_id"] == "sensor.victron_mk3_ac_output_power"


def test_select_relevant_entities_expands_variant_families_for_group_prompts():
    """Group prompts should keep sibling entity variants together."""
    entities = [
        {
            "entity_id": "sensor.victron_mk3_ac_output_voltage",
            "name": "AC Output Voltage",
            "domain": "sensor",
            "state": "230",
            "device_class": "voltage",
        },
        {
            "entity_id": "sensor.victron_mk3_ac_output_voltage_l2",
            "name": "AC Output Voltage L2",
            "domain": "sensor",
            "state": "231",
            "device_class": "voltage",
        },
        {
            "entity_id": "sensor.victron_mk3_ac_output_voltage_l3",
            "name": "AC Output Voltage L3",
            "domain": "sensor",
            "state": "229",
            "device_class": "voltage",
        },
        {
            "entity_id": "sensor.victron_mk3_ac_output_power",
            "name": "AC Output Power",
            "domain": "sensor",
            "state": "1500",
            "device_class": "power",
        },
    ]

    result = select_relevant_entities(
        "Monitor all three AC output phases and warn if any single phase voltage drops below 210 volts",
        entities,
        max_entities=4,
        fallback_entities=0,
    )

    entity_ids = [entity["entity_id"] for entity in result]
    assert "sensor.victron_mk3_ac_output_voltage" in entity_ids
    assert "sensor.victron_mk3_ac_output_voltage_l2" in entity_ids
    assert "sensor.victron_mk3_ac_output_voltage_l3" in entity_ids


def test_relevant_domain_matches_strip_clause_noise_from_automation_phrases():
    """Automation concept extraction should ignore wrapper words around the concept."""
    entities = [
        {
            "entity_id": "automation.electricity_balance_above_ps1",
            "name": "Electricity balance ABOVE £1",
            "domain": "automation",
            "state": "on",
            "device_class": None,
        },
        {
            "entity_id": "automation.electricity_balance_low",
            "name": "Electricity balance low",
            "domain": "automation",
            "state": "off",
            "device_class": None,
        },
        {
            "entity_id": "automation.left_lounge_light_on_during_bedtime",
            "name": "Left Lounge Light on during bedtime",
            "domain": "automation",
            "state": "off",
            "device_class": None,
        },
    ]

    result = _relevant_domain_matches(
        "Don't run any of this if the electricity balance automation is already active.",
        entities,
        "automation",
    )

    assert [entity["entity_id"] for entity in result] == [
        "automation.electricity_balance_above_ps1",
        "automation.electricity_balance_low",
    ]


def test_select_relevant_entities_prefers_notify_services_over_named_device_sensors():
    """Notification prompts should keep the actual notify target in scope."""
    entities = [
        {
            "entity_id": "notify.mobile_app_iphone_13",
            "name": "Notify Iphone 13",
            "domain": "notify",
            "state": "service",
            "device_class": "service",
        },
        {
            "entity_id": "sensor.iphone_13_audio_output",
            "name": "iPhone 13 Audio Output",
            "domain": "sensor",
            "state": "Built-in Speaker",
            "device_class": None,
        },
        {
            "entity_id": "sensor.victron_mk3_ac_output_power",
            "name": "AC Output Power",
            "domain": "sensor",
            "state": "1200",
            "device_class": "power",
        },
        {
            "entity_id": "sensor.victron_mk3_ac_output_voltage",
            "name": "AC Output Voltage",
            "domain": "sensor",
            "state": "230",
            "device_class": "voltage",
        },
    ]

    result = select_relevant_entities(
        "Notify my iPhone if AC output power goes above 1000 watts.",
        entities,
        max_entities=3,
        fallback_entities=0,
    )

    entity_ids = [entity["entity_id"] for entity in result]
    assert "notify.mobile_app_iphone_13" in entity_ids
    assert entity_ids.index("notify.mobile_app_iphone_13") < entity_ids.index(
        "sensor.iphone_13_audio_output"
    )


def test_select_relevant_entities_ignores_generic_single_word_noise():
    """Longer entity names should beat generic one-word names from the same clause."""
    entities = [
        {
            "entity_id": "switch.victron_mk3_battery_monitor",
            "name": "Battery Monitor",
            "domain": "switch",
            "state": "on",
            "device_class": None,
        },
        {
            "entity_id": "sensor.random_battery",
            "name": "Battery",
            "domain": "sensor",
            "state": "90",
            "device_class": "battery",
        },
        {
            "entity_id": "switch.finger_robot_switch",
            "name": "Switch",
            "domain": "switch",
            "state": "off",
            "device_class": None,
        },
    ]

    result = select_relevant_entities(
        "Disable the battery monitor switch",
        entities,
        max_entities=2,
        fallback_entities=0,
    )

    assert result[0]["entity_id"] == "switch.victron_mk3_battery_monitor"


def test_select_relevant_entities_prefers_named_automation_concepts():
    """Specific automation concepts should not be drowned out by generic action words."""
    entities = [
        {
            "entity_id": "automation.electricity_balance_above_ps1",
            "name": "Electricity balance ABOVE £1",
            "domain": "automation",
            "state": "on",
            "device_class": None,
        },
        {
            "entity_id": "automation.electricity_balance_low",
            "name": "Electricity balance low",
            "domain": "automation",
            "state": "on",
            "device_class": None,
        },
        {
            "entity_id": "automation.start_auto_wash_and_dry",
            "name": "Turn Off Switch When Wash Complete",
            "domain": "automation",
            "state": "off",
            "device_class": None,
        },
        {
            "entity_id": "automation.bedroom_mirror_off",
            "name": "Bedroom Mirror Off",
            "domain": "automation",
            "state": "on",
            "device_class": None,
        },
    ]

    result = select_relevant_entities(
        "Don't run any of this if the electricity balance automation is already active",
        entities,
        max_entities=2,
        fallback_entities=0,
    )

    assert [entity["entity_id"] for entity in result] == [
        "automation.electricity_balance_above_ps1",
        "automation.electricity_balance_low",
    ]


def test_select_relevant_entities_keeps_semantic_sensor_families_and_notify_targets():
    """Complex measurement prompts should retain the full relevant sensor families."""
    entities = [
        {
            "entity_id": "sensor.victron_mk3_ac_output_voltage",
            "name": "AC Output Voltage",
            "domain": "sensor",
            "state": "230",
            "device_class": "voltage",
        },
        {
            "entity_id": "sensor.victron_mk3_ac_output_voltage_l2",
            "name": "AC Output Voltage L2",
            "domain": "sensor",
            "state": "229",
            "device_class": "voltage",
        },
        {
            "entity_id": "sensor.victron_mk3_ac_output_voltage_l3",
            "name": "AC Output Voltage L3",
            "domain": "sensor",
            "state": "228",
            "device_class": "voltage",
        },
        {
            "entity_id": "sensor.victron_mk3_ac_output_current",
            "name": "AC Output Current",
            "domain": "sensor",
            "state": "9",
            "device_class": "current",
        },
        {
            "entity_id": "sensor.victron_mk3_ac_output_current_l2",
            "name": "AC Output Current L2",
            "domain": "sensor",
            "state": "10",
            "device_class": "current",
        },
        {
            "entity_id": "sensor.victron_mk3_ac_output_current_l3",
            "name": "AC Output Current L3",
            "domain": "sensor",
            "state": "11",
            "device_class": "current",
        },
        {
            "entity_id": "sensor.victron_mk3_ac_output_power",
            "name": "AC Output Power",
            "domain": "sensor",
            "state": "1200",
            "device_class": "power",
        },
        {
            "entity_id": "automation.electricity_balance_above_ps1",
            "name": "Electricity balance ABOVE £1",
            "domain": "automation",
            "state": "on",
            "device_class": None,
        },
        {
            "entity_id": "notify.mobile_app_iphone_13",
            "name": "Notify Iphone 13",
            "domain": "notify",
            "state": "service",
            "device_class": "service",
        },
    ]

    result = select_relevant_entities(
        (
            "Monitor all three AC output phases. If any single phase voltage drops "
            "below 210 volts or any single phase current exceeds 15 amps, notify my "
            "iPhone if total AC output power stays above 100 watts."
        ),
        entities,
        max_entities=9,
        fallback_entities=0,
    )

    entity_ids = {entity["entity_id"] for entity in result}
    assert "sensor.victron_mk3_ac_output_voltage" in entity_ids
    assert "sensor.victron_mk3_ac_output_voltage_l2" in entity_ids
    assert "sensor.victron_mk3_ac_output_voltage_l3" in entity_ids
    assert "sensor.victron_mk3_ac_output_current" in entity_ids
    assert "sensor.victron_mk3_ac_output_current_l2" in entity_ids
    assert "sensor.victron_mk3_ac_output_current_l3" in entity_ids
    assert "sensor.victron_mk3_ac_output_power" in entity_ids
    assert "automation.electricity_balance_above_ps1" in entity_ids
    assert "notify.mobile_app_iphone_13" in entity_ids


def test_select_relevant_entities_prefers_scope_specific_output_entities():
    """Semantic matching should stay on the requested output family instead of nearby input/battery sensors."""
    entities = [
        {
            "entity_id": "sensor.victron_mk3_ac_output_voltage",
            "name": "AC Output Voltage",
            "domain": "sensor",
            "state": "230",
            "device_class": "voltage",
        },
        {
            "entity_id": "sensor.victron_mk3_ac_input_voltage",
            "name": "AC Input Voltage",
            "domain": "sensor",
            "state": "228",
            "device_class": "voltage",
        },
        {
            "entity_id": "sensor.victron_mk3_battery_voltage",
            "name": "Battery Voltage",
            "domain": "sensor",
            "state": "13.2",
            "device_class": "voltage",
        },
        {
            "entity_id": "sensor.victron_mk3_ac_output_power",
            "name": "AC Output Power",
            "domain": "sensor",
            "state": "1200",
            "device_class": "power",
        },
        {
            "entity_id": "sensor.victron_mk3_ac_input_power",
            "name": "AC Input Power",
            "domain": "sensor",
            "state": "800",
            "device_class": "power",
        },
        {
            "entity_id": "sensor.victron_mk3_battery_power",
            "name": "Battery Power",
            "domain": "sensor",
            "state": "200",
            "device_class": "power",
        },
    ]

    result = select_relevant_entities(
        "Alert me if any Victron AC output voltage drops below 210 volts or AC output power stays above 100 watts.",
        entities,
        max_entities=4,
        fallback_entities=0,
    )

    assert [entity["entity_id"] for entity in result[:2]] == [
        "sensor.victron_mk3_ac_output_voltage",
        "sensor.victron_mk3_ac_output_power",
    ]


def test_select_relevant_entities_matches_variant_base_names_from_prompt():
    """Base target phrases should pull in sibling left/right style variants."""
    entities = [
        {
            "entity_id": "light.lounge_strip_lights_left",
            "name": "Lounge Strip Lights Left",
            "domain": "light",
            "state": "off",
            "device_class": None,
        },
        {
            "entity_id": "light.lounge_strip_lights_right",
            "name": "Lounge Strip Lights Right",
            "domain": "light",
            "state": "off",
            "device_class": None,
        },
        {
            "entity_id": "light.bedroom_strip_light_left",
            "name": "Bedroom Strip Light Left",
            "domain": "light",
            "state": "off",
            "device_class": None,
        },
    ]

    result = select_relevant_entities(
        "Turn off both lounge strip lights and the bedroom strip light.",
        entities,
        max_entities=3,
        fallback_entities=0,
    )

    assert [entity["entity_id"] for entity in result] == [
        "light.lounge_strip_lights_left",
        "light.lounge_strip_lights_right",
        "light.bedroom_strip_light_left",
    ]


def test_select_relevant_entities_falls_back_when_prompt_has_no_matches():
    """When nothing matches the prompt, the selector should still return a stable slice."""
    entities = [
        {"entity_id": "light.office", "name": "Office Light", "domain": "light", "state": "off", "device_class": None},
        {"entity_id": "switch.fan", "name": "Fan", "domain": "switch", "state": "off", "device_class": None},
        {"entity_id": "sensor.outdoor_temp", "name": "Outdoor Temperature", "domain": "sensor", "state": "12", "device_class": "temperature"},
    ]

    result = select_relevant_entities(
        "Play jazz in the garden",
        entities,
        max_entities=2,
        fallback_entities=1,
    )

    assert result == entities[:2]
