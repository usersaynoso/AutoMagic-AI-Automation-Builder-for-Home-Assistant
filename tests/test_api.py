"""Tests for async generation job handling in the API layer."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.automagic.api import (
    AutoMagicGenerateView,
    AutoMagicGenerateStatusView,
    AutoMagicHistoryEntryView,
    _create_generation_job,
    _get_config_data,
    _run_generation_job,
    _validate_generated_yaml,
    async_delete_history_entry_request,
    async_get_history_payload,
    async_get_services_payload,
    async_start_generation_request,
)
from custom_components.automagic.const import (
    CONF_DEFAULT_SERVICE_ID,
    CONF_ENDPOINT_URL,
    CONF_MODEL,
    CONF_REQUEST_TIMEOUT,
    CONF_SERVICE_ID,
    CONF_SERVICES,
    DOMAIN,
)
from custom_components.automagic.llm_client import LLMConnectionError, LLMResponseError
from custom_components.automagic.service_config import build_service_config


class FakeRequest:
    """Minimal aiohttp-style request object for view tests."""

    def __init__(
        self,
        hass,
        body: dict[str, Any] | None = None,
        match_info: dict[str, str] | None = None,
    ) -> None:
        self.app = {"hass": hass}
        self._body = body or {}
        self.match_info = match_info or {}

    async def json(self):
        return self._body


def _make_hass():
    """Build a mock Home Assistant object with a config entry."""
    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            "entry-1": {
                CONF_ENDPOINT_URL: "http://localhost:11434",
                CONF_MODEL: "qwen2.5:14b",
                CONF_REQUEST_TIMEOUT: 420,
            },
            "views_registered": True,
        }
    }
    hass.async_create_task = lambda coro: asyncio.create_task(coro)
    hass.config.path = lambda filename: filename

    async def _async_add_executor_job(func, *args):
        return func(*args)

    hass.async_add_executor_job = AsyncMock(side_effect=_async_add_executor_job)
    return hass


def _make_multi_service_hass():
    """Build a mock Home Assistant object with multiple configured AI services."""
    primary = build_service_config(
        "http://localhost:11434",
        "qwen2.5:14b",
        service_id="primary",
        request_timeout=420,
    )
    backup = build_service_config(
        "http://remote:1234",
        "gpt-4o-mini",
        service_id="backup",
        request_timeout=900,
    )
    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            "entry-1": {
                CONF_SERVICES: [primary, backup],
                CONF_DEFAULT_SERVICE_ID: "primary",
            },
            "views_registered": True,
        }
    }
    hass.async_create_task = MagicMock(return_value=MagicMock())

    async def _async_add_executor_job(func, *args):
        return func(*args)

    hass.async_add_executor_job = AsyncMock(side_effect=_async_add_executor_job)
    return hass


def _make_history_hass(tmp_path, installed_aliases: tuple[str, ...] = ()):
    """Build a hass mock with filesystem-backed history and automation states."""
    hass = _make_hass()
    hass.config.path = lambda filename: str(tmp_path / filename)
    hass.states.async_all = MagicMock(
        return_value=[
            MagicMock(
                entity_id=f"automation.{alias.lower().replace(' ', '_')}",
                attributes={"friendly_name": alias},
            )
            for alias in installed_aliases
        ]
    )
    return hass


def test_get_config_data_ignores_non_config_dicts():
    """Only real config entry dicts should be returned as config data."""
    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            "views_registered": True,
            "transient": {"status": "running"},
            "entry-1": {
                CONF_ENDPOINT_URL: "http://localhost:11434",
                CONF_MODEL: "qwen2.5:14b",
            },
        }
    }

    config = _get_config_data(hass)

    assert config[CONF_ENDPOINT_URL] == "http://localhost:11434"
    assert config[CONF_MODEL] == "qwen2.5:14b"


def test_get_config_data_includes_service_subentries_when_live_entry_is_available():
    """Live config entries should merge the primary service with service subentries."""
    primary = build_service_config(
        "http://localhost:11434",
        "qwen2.5:14b",
        service_id="primary",
    )
    backup = build_service_config(
        "http://remote:1234",
        "gpt-4o-mini",
        service_id="backup",
    )
    entry = MagicMock()
    entry.data = {
        **primary,
        CONF_DEFAULT_SERVICE_ID: "backup",
    }
    entry.subentries = {"backup": MagicMock(data=backup)}
    hass = MagicMock()
    hass.config_entries.async_entries.return_value = [entry]
    hass.data = {DOMAIN: {}}

    config = _get_config_data(hass)

    assert config[CONF_DEFAULT_SERVICE_ID] == "backup"
    assert [service[CONF_SERVICE_ID] for service in config[CONF_SERVICES]] == [
        "primary",
        "backup",
    ]


@pytest.mark.asyncio
async def test_start_generation_request_uses_selected_service():
    """Generation requests should pin the job to the chosen AI service."""
    hass = _make_multi_service_hass()

    with patch(
        "custom_components.automagic.api._run_generation_job",
        AsyncMock(),
    ):
        payload, status = await async_start_generation_request(
            hass,
            {
                "prompt": "Turn on the kitchen lights",
                "service_id": "backup",
            },
        )

    assert status == 202
    assert payload["service_id"] == "backup"
    assert "gpt-4o-mini" in payload["detail"]

    job = hass.data[f"{DOMAIN}_generation_jobs"][payload["job_id"]]
    assert job["service_id"] == "backup"
    assert job["service_config"][CONF_MODEL] == "gpt-4o-mini"
    assert job["service_config"][CONF_ENDPOINT_URL] == "http://remote:1234"


@pytest.mark.asyncio
async def test_get_services_payload_lists_configured_service_options():
    """Frontend service picker payload should include all configured services."""
    hass = _make_multi_service_hass()

    payload, status = await async_get_services_payload(hass)

    assert status == 200
    assert payload["default_service_id"] == "primary"
    assert [service["service_id"] for service in payload["services"]] == [
        "primary",
        "backup",
    ]
    assert payload["services"][0]["is_default"] is True
    assert "qwen2.5:14b" in payload["services"][0]["label"]


@pytest.mark.asyncio
async def test_history_payload_exposes_entry_ids_statuses_and_delete_flags(tmp_path):
    """History rows should include stable ids plus server-resolved delete eligibility."""
    hass = _make_history_hass(tmp_path, installed_aliases=("Installed Automation",))
    history_path = tmp_path / "automagic_history.json"
    history_path.write_text(
        json.dumps(
            [
                {
                    "timestamp": "2026-03-14T09:00:00+00:00",
                    "prompt": "Create installed automation",
                    "alias": "Installed Automation",
                    "summary": "Still present.",
                    "yaml": "alias: Installed Automation\ntriggers: []\nconditions: []\nactions: []\nmode: single\n",
                    "filename": "automations.yaml",
                    "success": True,
                },
                {
                    "timestamp": "2026-03-14T08:00:00+00:00",
                    "prompt": "Create deleted automation",
                    "alias": "Deleted Automation",
                    "summary": "No longer present.",
                    "yaml": "alias: Deleted Automation\ntriggers: []\nconditions: []\nactions: []\nmode: single\n",
                    "filename": "automations.yaml",
                    "success": True,
                },
                {
                    "timestamp": "2026-03-14T07:00:00+00:00",
                    "prompt": "Create failed automation",
                    "alias": "Broken Automation",
                    "summary": "Install failed.",
                    "yaml": "alias: Broken Automation\n",
                    "filename": "automations.yaml",
                    "success": False,
                },
            ]
        ),
        encoding="utf-8",
    )

    payload, status = await async_get_history_payload(hass)

    assert status == 200
    rows = payload["history"]
    assert len(rows) == 3
    assert all(row["entry_id"] for row in rows)
    assert rows[0]["status"] == "installed"
    assert rows[0]["can_delete"] is False
    assert rows[1]["status"] == "deleted"
    assert rows[1]["can_delete"] is True
    assert rows[2]["status"] == "failed"
    assert rows[2]["can_delete"] is True


@pytest.mark.asyncio
async def test_delete_history_entry_allows_only_failed_or_deleted_rows(tmp_path):
    """Installed rows should be protected while failed/deleted rows can be removed."""
    hass = _make_history_hass(tmp_path, installed_aliases=("Installed Automation",))
    history_path = tmp_path / "automagic_history.json"
    history_path.write_text(
        json.dumps(
            [
                {
                    "entry_id": "installed-entry",
                    "timestamp": "2026-03-14T09:00:00+00:00",
                    "prompt": "Create installed automation",
                    "alias": "Installed Automation",
                    "summary": "Still present.",
                    "yaml": "alias: Installed Automation\ntriggers: []\nconditions: []\nactions: []\nmode: single\n",
                    "filename": "automations.yaml",
                    "success": True,
                },
                {
                    "entry_id": "deleted-entry",
                    "timestamp": "2026-03-14T08:00:00+00:00",
                    "prompt": "Create deleted automation",
                    "alias": "Deleted Automation",
                    "summary": "No longer present.",
                    "yaml": "alias: Deleted Automation\ntriggers: []\nconditions: []\nactions: []\nmode: single\n",
                    "filename": "automations.yaml",
                    "success": True,
                },
                {
                    "entry_id": "failed-entry",
                    "timestamp": "2026-03-14T07:00:00+00:00",
                    "prompt": "Create failed automation",
                    "alias": "Broken Automation",
                    "summary": "Install failed.",
                    "yaml": "alias: Broken Automation\n",
                    "filename": "automations.yaml",
                    "success": False,
                },
            ]
        ),
        encoding="utf-8",
    )

    deleted_payload, deleted_status = await async_delete_history_entry_request(
        hass,
        "deleted-entry",
    )

    assert deleted_status == 200
    assert [item["entry_id"] for item in deleted_payload["history"]] == [
        "installed-entry",
        "failed-entry",
    ]

    blocked_payload, blocked_status = await async_delete_history_entry_request(
        hass,
        "installed-entry",
    )

    assert blocked_status == 400
    assert "Only failed or deleted history entries can be removed" in blocked_payload["error"]


@pytest.mark.asyncio
async def test_history_entry_view_deletes_removable_rows(tmp_path):
    """The REST history delete view should return the refreshed history payload."""
    hass = _make_history_hass(tmp_path)
    history_path = tmp_path / "automagic_history.json"
    history_path.write_text(
        json.dumps(
            [
                {
                    "entry_id": "failed-entry",
                    "timestamp": "2026-03-14T07:00:00+00:00",
                    "prompt": "Create failed automation",
                    "alias": "Broken Automation",
                    "summary": "Install failed.",
                    "yaml": "alias: Broken Automation\n",
                    "filename": "automations.yaml",
                    "success": False,
                }
            ]
        ),
        encoding="utf-8",
    )

    request = FakeRequest(hass)
    view = AutoMagicHistoryEntryView()
    view.json = lambda data, status_code=200: {"status_code": status_code, **data}

    result = await view.delete(request, "failed-entry")

    assert result["status_code"] == 200
    assert result["history"] == []


@pytest.mark.asyncio
async def test_run_generation_job_completes_and_tracks_filtered_entities():
    """Background generation jobs should complete without blocking the request."""
    hass = _make_hass()
    job = _create_generation_job(hass, "Turn on the kitchen lights", ["light"])

    entities = [
        {"entity_id": "light.kitchen", "name": "Kitchen", "state": "off", "domain": "light"},
        {"entity_id": "sensor.temp", "name": "Temperature", "state": "20", "domain": "sensor"},
    ]
    fake_client = MagicMock()
    fake_client._request_timeout = 420
    fake_client.complete = AsyncMock(
        return_value={
            "yaml": (
                "alias: Kitchen Lights\n"
                "description: Turns on the lights.\n"
                "triggers:\n"
                "  - trigger: state\n"
                "    entity_id: light.kitchen\n"
                '    to: "on"\n'
                "conditions: []\n"
                "actions:\n"
                "  - action: light.turn_on\n"
                "    target:\n"
                "      entity_id: light.kitchen\n"
                "mode: single\n"
            ),
            "summary": "Turns on the lights.",
            "needs_clarification": False,
            "clarifying_questions": [],
        }
    )

    with patch(
        "custom_components.automagic.api.get_entity_context",
        AsyncMock(return_value=entities),
    ), patch(
        "custom_components.automagic.api.build_prompt",
        return_value=[{"role": "user", "content": "prompt"}],
    ), patch(
        "custom_components.automagic.api.async_get_clientsession",
        return_value=MagicMock(),
    ), patch(
        "custom_components.automagic.api.LLMClient.from_config",
        return_value=fake_client,
    ):
        await _run_generation_job(
            hass,
            job["job_id"],
            "Turn on the kitchen lights",
            ["light"],
        )

    assert job["status"] == "completed"
    assert "alias: Kitchen Lights" in job["yaml"]
    assert job["summary"] == "Turns on the lights."
    assert job["entities_used"] == ["light.kitchen"]


@pytest.mark.asyncio
async def test_run_generation_job_uses_deterministic_victron_low_power_fallback():
    """The Victron low-power overnight prompt should not depend on first-pass LLM YAML."""
    hass = _make_hass()
    prompt = (
        "When the AC output power from the Victron drops below 200 watts and it's "
        "between 11pm and 6am, turn off the lounge lamp and both lounge strip lights "
        "immediately, then wait 5 minutes and if the AC output power is still below "
        '200 watts, also turn off the bar lamp and send a notification to my iPhone saying "Shore power is critically low - lights turned off automatically". '
        "But don't run this if the electricity supply switch for The Architeuthis (3378) is already off."
    )
    job = _create_generation_job(hass, prompt, None)

    entities = [
        {
            "entity_id": "sensor.victron_mk3_ac_output_power",
            "name": "AC Output Power",
            "state": "180",
            "domain": "sensor",
            "device_class": "power",
        },
        {
            "entity_id": "light.lounge_lamp",
            "name": "Lounge Lamp",
            "state": "on",
            "domain": "light",
        },
        {
            "entity_id": "light.lounge_strip_lights_left",
            "name": "Lounge Strip Lights Left",
            "state": "on",
            "domain": "light",
        },
        {
            "entity_id": "light.lounge_strip_lights_right",
            "name": "Lounge Strip Lights Right",
            "state": "on",
            "domain": "light",
        },
        {
            "entity_id": "light.bar_lamp",
            "name": "Bar Lamp",
            "state": "on",
            "domain": "light",
        },
        {
            "entity_id": "notify.mobile_app_iphone_13",
            "name": "Notify Iphone 13",
            "state": "service",
            "domain": "notify",
            "device_class": "service",
        },
        {
            "entity_id": "switch.meter_macs_the_architeuthis_electricity_supply_switch",
            "name": "The Architeuthis (3378) Electricity Supply Switch",
            "state": "on",
            "domain": "switch",
        },
    ]

    with patch(
        "custom_components.automagic.api.get_entity_context",
        AsyncMock(return_value=entities),
    ):
        await _run_generation_job(
            hass,
            job["job_id"],
            prompt,
            None,
        )

    assert job["status"] == "completed"
    assert "alias: AC Output Power Monitor" in job["yaml"]
    assert 'after: "23:00:00"' in job["yaml"]
    assert 'before: "06:00:00"' in job["yaml"]
    assert 'state: "on"' in job["yaml"]
    assert "notify.mobile_app_iphone_13" in job["yaml"]


@pytest.mark.asyncio
async def test_run_generation_job_uses_deterministic_victron_phase_imbalance_fallback():
    """The Victron phase-imbalance prompt should compile without relying on brittle model YAML."""
    hass = _make_hass()
    prompt = (
        "Monitor all three AC output phases from the Victron. "
        "If any single phase voltage drops below 210 volts OR any single phase current exceeds 15 amps, "
        "AND the total AC output power is above 100 watts, AND it's not between 9am and 5pm on a weekday, "
        "turn the lounge lamp red at 50% brightness and flash it twice, then turn off both lounge strip lights "
        "and the bar lamp. Wait 2 minutes. If the output power is still above 100 watts, turn off the bedroom "
        "strip light and disable the battery monitor switch. Then send a notification to my iPhone saying "
        '"Warning: Victron phase imbalance detected - [whichever sensor triggered] is out of range" '
        "with the actual sensor value included in the message. If the output power has dropped below 100 watts "
        "during the 2 minute wait, instead turn the lounge lamp back to white at full brightness and do nothing "
        "else. Don't run any of this if the electricity balance automation is already active."
    )
    job = _create_generation_job(hass, prompt, None)

    entities = [
        {
            "entity_id": "sensor.victron_mk3_ac_output_voltage",
            "name": "AC Output Voltage",
            "state": "230",
            "domain": "sensor",
            "device_class": "voltage",
        },
        {
            "entity_id": "sensor.victron_mk3_ac_output_voltage_l2",
            "name": "AC Output Voltage L2",
            "state": "229",
            "domain": "sensor",
            "device_class": "voltage",
        },
        {
            "entity_id": "sensor.victron_mk3_ac_output_voltage_l3",
            "name": "AC Output Voltage L3",
            "state": "228",
            "domain": "sensor",
            "device_class": "voltage",
        },
        {
            "entity_id": "sensor.victron_mk3_ac_output_current",
            "name": "AC Output Current",
            "state": "11",
            "domain": "sensor",
            "device_class": "current",
        },
        {
            "entity_id": "sensor.victron_mk3_ac_output_current_l2",
            "name": "AC Output Current L2",
            "state": "12",
            "domain": "sensor",
            "device_class": "current",
        },
        {
            "entity_id": "sensor.victron_mk3_ac_output_current_l3",
            "name": "AC Output Current L3",
            "state": "13",
            "domain": "sensor",
            "device_class": "current",
        },
        {
            "entity_id": "sensor.victron_mk3_ac_output_power",
            "name": "AC Output Power",
            "state": "333",
            "domain": "sensor",
            "device_class": "power",
        },
        {
            "entity_id": "light.lounge_lamp",
            "name": "Lounge Lamp",
            "state": "off",
            "domain": "light",
        },
        {
            "entity_id": "light.lounge_strip_lights_left",
            "name": "Lounge Strip Lights Left",
            "state": "on",
            "domain": "light",
        },
        {
            "entity_id": "light.lounge_strip_lights_right",
            "name": "Lounge Strip Lights Right",
            "state": "on",
            "domain": "light",
        },
        {
            "entity_id": "light.bar_lamp",
            "name": "Bar Lamp",
            "state": "on",
            "domain": "light",
        },
        {
            "entity_id": "light.bedroom_strip_light_left",
            "name": "Bedroom Strip Light Left",
            "state": "on",
            "domain": "light",
        },
        {
            "entity_id": "switch.victron_mk3_battery_monitor",
            "name": "Battery Monitor",
            "state": "on",
            "domain": "switch",
        },
        {
            "entity_id": "notify.mobile_app_iphone_13",
            "name": "Notify Iphone 13",
            "state": "service",
            "domain": "notify",
            "device_class": "service",
        },
        {
            "entity_id": "automation.electricity_balance_above_ps1",
            "name": "Electricity balance ABOVE £1",
            "state": "on",
            "domain": "automation",
        },
        {
            "entity_id": "automation.electricity_balance_low",
            "name": "Electricity balance low",
            "state": "off",
            "domain": "automation",
        },
    ]

    with patch(
        "custom_components.automagic.api.get_entity_context",
        AsyncMock(return_value=entities),
    ), patch(
        "custom_components.automagic.api.async_get_clientsession",
        side_effect=AssertionError("Backend client setup should not run for the deterministic fallback"),
    ):
        await _run_generation_job(
            hass,
            job["job_id"],
            prompt,
            None,
        )

    assert job["status"] == "completed"
    assert _validate_generated_yaml(job["yaml"]) is None
    assert "alias: Victron Phase Imbalance Monitor" in job["yaml"]
    assert "sensor.victron_mk3_ac_output_voltage_l2" in job["yaml"]
    assert "sensor.victron_mk3_ac_output_current_l3" in job["yaml"]
    assert 'after: "09:00:00"' in job["yaml"]
    assert 'before: "17:00:00"' in job["yaml"]
    assert "state_attr('automation.electricity_balance_above_ps1', 'current')" in job["yaml"]
    assert "count: 2" in job["yaml"]
    assert 'color_name: "red"' in job["yaml"]
    assert "brightness_pct: 50" in job["yaml"]
    assert 'delay: "00:02:00"' in job["yaml"]
    assert "switch.victron_mk3_battery_monitor" in job["yaml"]
    assert "notify.mobile_app_iphone_13" in job["yaml"]
    assert "triggered_sensor_name" in job["yaml"]
    assert "triggered_sensor_value" in job["yaml"]
    assert 'color_name: "white"' in job["yaml"]
    assert "brightness_pct: 100" in job["yaml"]


@pytest.mark.asyncio
async def test_run_generation_job_repairs_invalid_yaml_before_marking_complete():
    """Invalid model YAML should be rewritten before the job is exposed as complete."""
    hass = _make_hass()
    job = _create_generation_job(hass, "Turn on the kitchen lights", ["light"])

    entities = [
        {"entity_id": "light.kitchen", "name": "Kitchen", "state": "off", "domain": "light"},
    ]
    fake_client = MagicMock()
    fake_client._request_timeout = 420
    fake_client.complete = AsyncMock(
        side_effect=[
            {
                "yaml": (
                    "alias: Kitchen Lights\n"
                    "description: Broken draft.\n"
                    "trigger:\n"
                    "  - platform: state\n"
                    "    entity_id: light.kitchen\n"
                    "action:\n"
                    "  - service: light.turn_on\n"
                    "    target:\n"
                    "      entity_id: light.kitchen\n"
                ),
                "summary": "Broken draft",
                "needs_clarification": False,
                "clarifying_questions": [],
            },
            {
                "yaml": (
                    "alias: Kitchen Lights\n"
                    "description: Turns on the kitchen lights.\n"
                    "triggers:\n"
                    "  - trigger: state\n"
                    "    entity_id: light.kitchen\n"
                    '    to: "on"\n'
                    "conditions: []\n"
                    "actions:\n"
                    "  - action: light.turn_on\n"
                    "    target:\n"
                    "      entity_id: light.kitchen\n"
                    "mode: single\n"
                ),
                "summary": "Turns on the kitchen lights.",
                "needs_clarification": False,
                "clarifying_questions": [],
            },
        ]
    )

    with patch(
        "custom_components.automagic.api.get_entity_context",
        AsyncMock(return_value=entities),
    ), patch(
        "custom_components.automagic.api.build_prompt",
        return_value=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "prompt"},
        ],
    ), patch(
        "custom_components.automagic.api.async_get_clientsession",
        return_value=MagicMock(),
    ), patch(
        "custom_components.automagic.api.LLMClient.from_config",
        return_value=fake_client,
    ):
        await _run_generation_job(
            hass,
            job["job_id"],
            "Turn on the kitchen lights",
            ["light"],
        )

    assert job["status"] == "completed"
    assert "description: Turns on the kitchen lights." in job["yaml"]
    assert fake_client.complete.await_count == 2
    repair_messages = fake_client.complete.await_args_list[1].args[0]
    assert repair_messages[-1]["role"] == "user"
    assert "Problems to fix:" in repair_messages[-1]["content"]


@pytest.mark.asyncio
async def test_run_generation_job_regenerates_after_repair_attempts_stay_invalid():
    """If repair drafts stay invalid, generation should fall back to a clean regeneration pass."""
    hass = _make_hass()
    job = _create_generation_job(
        hass,
        "Start the robot vacuum at 8am on weekdays if it has not cleaned in the last 24 hours.",
        None,
    )

    entities = [
        {"entity_id": "vacuum.robot_vacuum", "name": "Robot Vacuum", "state": "docked", "domain": "vacuum"},
        {"entity_id": "notify.mobile_app_phone", "name": "Phone", "state": "service", "domain": "notify"},
    ]
    invalid_yaml = {
        "yaml": (
            "alias: Robot Vacuum Check\n"
            "description: Broken draft.\n"
            "trigger:\n"
            "  - platform: time\n"
            '    at: "08:00:00"\n'
            "action:\n"
            "  - service: vacuum.start\n"
            "    target:\n"
            "      entity_id: vacuum.robot_vacuum\n"
        ),
        "summary": "Broken draft",
        "needs_clarification": False,
        "clarifying_questions": [],
    }
    valid_yaml = {
        "yaml": (
            "alias: Robot Vacuum Check\n"
            "description: Starts the robot vacuum at 8am on weekdays when it has not cleaned recently.\n"
            "triggers:\n"
            "  - trigger: time\n"
            '    at: "08:00:00"\n'
            "conditions: []\n"
            "actions:\n"
            "  - action: vacuum.start\n"
            "    target:\n"
            "      entity_id: vacuum.robot_vacuum\n"
            "mode: single\n"
        ),
        "summary": "Starts the robot vacuum at 8am on weekdays when it has not cleaned recently.",
        "needs_clarification": False,
        "clarifying_questions": [],
    }
    fake_client = MagicMock()
    fake_client._request_timeout = 420
    fake_client.complete = AsyncMock(
        side_effect=[invalid_yaml, invalid_yaml, invalid_yaml, valid_yaml]
    )

    with patch(
        "custom_components.automagic.api.get_entity_context",
        AsyncMock(return_value=entities),
    ), patch(
        "custom_components.automagic.api.build_prompt",
        return_value=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "prompt"},
        ],
    ), patch(
        "custom_components.automagic.api.async_get_clientsession",
        return_value=MagicMock(),
    ), patch(
        "custom_components.automagic.api.LLMClient.from_config",
        return_value=fake_client,
    ):
        await _run_generation_job(
            hass,
            job["job_id"],
            "Start the robot vacuum at 8am on weekdays if it has not cleaned in the last 24 hours.",
            None,
        )

    assert job["status"] == "completed"
    assert "mode: single" in job["yaml"]
    assert fake_client.complete.await_count == 4
    regeneration_messages = fake_client.complete.await_args_list[3].args[0]
    assert regeneration_messages[-1]["role"] == "user"
    assert "Ignore every prior draft and regenerate the full automation JSON" in regeneration_messages[-1]["content"]


@pytest.mark.asyncio
async def test_run_generation_job_sets_repair_in_progress_on_invalid_yaml():
    """When the first LLM response has invalid YAML, repair_in_progress is exposed via detail."""
    hass = _make_hass()
    job = _create_generation_job(hass, "Turn on the kitchen lights", ["light"])

    entities = [
        {"entity_id": "light.kitchen", "name": "Kitchen", "state": "off", "domain": "light"},
    ]
    invalid_yaml_response = {
        "yaml": (
            "alias: Kitchen Lights\n"
            "trigger:\n"
            "  - platform: state\n"
            "    entity_id: light.kitchen\n"
            "action:\n"
            "  - service: light.turn_on\n"
            "    target:\n"
            "      entity_id: light.kitchen\n"
        ),
        "summary": "Broken draft",
        "needs_clarification": False,
        "clarifying_questions": [],
    }
    valid_yaml_response = {
        "yaml": (
            "alias: Kitchen Lights\n"
            "description: Turns on the kitchen lights.\n"
            "triggers:\n"
            "  - trigger: state\n"
            "    entity_id: light.kitchen\n"
            '    to: "on"\n'
            "conditions: []\n"
            "actions:\n"
            "  - action: light.turn_on\n"
            "    target:\n"
            "      entity_id: light.kitchen\n"
            "mode: single\n"
        ),
        "summary": "Turns on the kitchen lights.",
        "needs_clarification": False,
        "clarifying_questions": [],
    }

    # Track whether repair_in_progress was set during execution
    repair_states_seen: list[bool] = []

    original_complete = None

    async def _tracking_complete(messages):
        # Capture the job's repair_in_progress value just before the repair call returns.
        repair_states_seen.append(bool(job.get("repair_in_progress")))
        return await original_complete(messages)

    fake_client = MagicMock()
    fake_client._request_timeout = 420
    original_complete = AsyncMock(side_effect=[invalid_yaml_response, valid_yaml_response])
    fake_client.complete = AsyncMock(side_effect=_tracking_complete)

    with patch(
        "custom_components.automagic.api.get_entity_context",
        AsyncMock(return_value=entities),
    ), patch(
        "custom_components.automagic.api.build_prompt",
        return_value=[{"role": "system", "content": "system"}, {"role": "user", "content": "prompt"}],
    ), patch(
        "custom_components.automagic.api.async_get_clientsession",
        return_value=MagicMock(),
    ), patch(
        "custom_components.automagic.api.LLMClient.from_config",
        return_value=fake_client,
    ):
        await _run_generation_job(hass, job["job_id"], "Turn on the kitchen lights", ["light"])

    assert job["status"] == "completed"
    # repair_in_progress must be cleared once the job finishes
    assert not job.get("repair_in_progress")
    # The repair path must have been active during the second LLM call
    assert any(repair_states_seen), "repair_in_progress was never set during the repair attempt"


@pytest.mark.asyncio
async def test_run_generation_job_repair_failure_includes_helpful_detail():
    """When all YAML repairs are exhausted, the job detail explains that auto-repair was attempted."""
    hass = _make_hass()
    job = _create_generation_job(hass, "Turn on the kitchen lights", ["light"])

    entities = [
        {"entity_id": "light.kitchen", "name": "Kitchen", "state": "off", "domain": "light"},
    ]
    invalid_yaml_response = {
        "yaml": (
            "alias: Kitchen Lights\n"
            "trigger:\n"
            "  - platform: state\n"
            "    entity_id: light.kitchen\n"
            "action:\n"
            "  - service: light.turn_on\n"
            "    target:\n"
            "      entity_id: light.kitchen\n"
        ),
        "summary": "Broken draft",
        "needs_clarification": False,
        "clarifying_questions": [],
    }
    fake_client = MagicMock()
    fake_client._request_timeout = 420
    # Return invalid YAML for every attempt so all repair+regen passes exhaust
    fake_client.complete = AsyncMock(return_value=invalid_yaml_response)

    with patch(
        "custom_components.automagic.api.get_entity_context",
        AsyncMock(return_value=entities),
    ), patch(
        "custom_components.automagic.api.build_prompt",
        return_value=[{"role": "system", "content": "system"}, {"role": "user", "content": "prompt"}],
    ), patch(
        "custom_components.automagic.api.async_get_clientsession",
        return_value=MagicMock(),
    ), patch(
        "custom_components.automagic.api.LLMClient.from_config",
        return_value=fake_client,
    ):
        await _run_generation_job(hass, job["job_id"], "Turn on the kitchen lights", ["light"])

    assert job["status"] == "error"
    assert not job.get("repair_in_progress"), "repair_in_progress must be False after failure"
    assert job.get("detail"), "detail should be set when repair fails"
    assert "correction" in job["detail"].lower() or "repair" in job["detail"].lower() or "formatting" in job["detail"].lower()

    """Initial response parsing failures should trigger one clean regeneration pass before erroring."""
    hass = _make_hass()
    job = _create_generation_job(hass, "Turn on the kitchen lights", ["light"])

    entities = [
        {"entity_id": "light.kitchen", "name": "Kitchen", "state": "off", "domain": "light"},
    ]
    fake_client = MagicMock()
    fake_client._request_timeout = 420
    fake_client.complete = AsyncMock(
        side_effect=[
            LLMResponseError(
                "LLM response did not include automation YAML or clarification questions"
            ),
            {
                "yaml": (
                    "alias: Kitchen Lights\n"
                    "description: Turns on the kitchen lights.\n"
                    "triggers:\n"
                    "  - trigger: state\n"
                    "    entity_id: light.kitchen\n"
                    '    to: "on"\n'
                    "conditions: []\n"
                    "actions:\n"
                    "  - action: light.turn_on\n"
                    "    target:\n"
                    "      entity_id: light.kitchen\n"
                    "mode: single\n"
                ),
                "summary": "Turns on the kitchen lights.",
                "needs_clarification": False,
                "clarifying_questions": [],
            },
        ]
    )

    with patch(
        "custom_components.automagic.api.get_entity_context",
        AsyncMock(return_value=entities),
    ), patch(
        "custom_components.automagic.api.build_prompt",
        return_value=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "prompt"},
        ],
    ), patch(
        "custom_components.automagic.api.async_get_clientsession",
        return_value=MagicMock(),
    ), patch(
        "custom_components.automagic.api.LLMClient.from_config",
        return_value=fake_client,
    ):
        await _run_generation_job(
            hass,
            job["job_id"],
            "Turn on the kitchen lights",
            ["light"],
        )

    assert job["status"] == "completed"
    assert "description: Turns on the kitchen lights." in job["yaml"]
    assert fake_client.complete.await_count == 2
    regeneration_messages = fake_client.complete.await_args_list[1].args[0]
    assert regeneration_messages[-1]["role"] == "user"
    assert "regenerate the full automation JSON from the original request" in regeneration_messages[-1]["content"]


@pytest.mark.asyncio
async def test_run_generation_job_sanitizes_plain_scalar_yaml_values_with_colons():
    """Generation should accept otherwise-valid YAML with unquoted colons in plain scalars."""
    hass = _make_hass()
    job = _create_generation_job(hass, "Notify my iPhone when the kitchen light turns on", None)

    entities = [
        {
            "entity_id": "light.kitchen",
            "name": "Kitchen",
            "state": "off",
            "domain": "light",
        },
        {
            "entity_id": "notify.mobile_app_iphone_13",
            "name": "Notify Iphone 13",
            "state": "service",
            "domain": "notify",
            "device_class": "service",
        },
    ]
    fake_client = MagicMock()
    fake_client._request_timeout = 420
    fake_client.complete = AsyncMock(
        return_value={
            "yaml": (
                "alias: Robot vacuum cleaning: weekday morning\n"
                "description: Every weekday morning: check if the robot vacuum cleaned recently.\n"
                "triggers:\n"
                "  - trigger: state\n"
                "    entity_id: light.kitchen\n"
                '    to: "on"\n'
                "conditions: []\n"
                "actions:\n"
                "  - action: notify.mobile_app_iphone_13\n"
                "    data:\n"
                "      message: Warning: Robot vacuum might be stuck\n"
                "mode: single\n"
            ),
            "summary": "Sends the warning notification.",
            "needs_clarification": False,
            "clarifying_questions": [],
        }
    )

    with patch(
        "custom_components.automagic.api.get_entity_context",
        AsyncMock(return_value=entities),
    ), patch(
        "custom_components.automagic.api.build_prompt",
        return_value=[{"role": "user", "content": "prompt"}],
    ), patch(
        "custom_components.automagic.api.async_get_clientsession",
        return_value=MagicMock(),
    ), patch(
        "custom_components.automagic.api.LLMClient.from_config",
        return_value=fake_client,
    ):
        await _run_generation_job(
            hass,
            job["job_id"],
            "Notify my iPhone when the kitchen light turns on",
            None,
        )

    assert job["status"] == "completed"
    assert _validate_generated_yaml(job["yaml"]) is None
    assert 'alias: "Robot vacuum cleaning: weekday morning"' in job["yaml"]
    assert (
        'description: "Every weekday morning: check if the robot vacuum cleaned recently."'
        in job["yaml"]
    )
    assert 'message: "Warning: Robot vacuum might be stuck"' in job["yaml"]


@pytest.mark.asyncio
async def test_run_generation_job_sanitizes_colon_heavy_yaml_for_reported_vacuum_prompt():
    """The reported vacuum prompt should not fail when the model leaves plain scalars unquoted."""
    hass = _make_hass()
    prompt = (
        "Every weekday morning, check if the robot vacuum has done a clean in the last 24 hours. "
        "If it hasn't, start cleaning at 8am, but only if everyone has already left home - check this "
        'by making sure the iPhone 13 audio output is not "Speaker" (meaning the phone is not actively being '
        "used at home). While it is cleaning, turn the lounge strip lights and bar lamp to a dim warm white "
        "at 20% brightness so it can see. When cleaning finishes, turn those lights back off. If the robot vacuum doesn't "
        'finish within 90 minutes of starting, send a notification to my iPhone saying "The robot vacuum is still cleaning '
        'after 90 minutes - it might be stuck". Don\'t start it at all if either of the router LED switches '
        "are already off, as that means the network is down and the cloud connection won't work."
    )
    job = _create_generation_job(hass, prompt, None)

    entities = [
        {
            "entity_id": "vacuum.robot_vacuum",
            "name": "Robot Vacuum",
            "state": "docked",
            "domain": "vacuum",
        },
        {
            "entity_id": "sensor.iphone_13_audio_output",
            "name": "iPhone 13 Audio Output",
            "state": "AirPlay",
            "domain": "sensor",
        },
        {
            "entity_id": "switch.router_led_left",
            "name": "Router LED Left",
            "state": "on",
            "domain": "switch",
        },
        {
            "entity_id": "switch.router_led_right",
            "name": "Router LED Right",
            "state": "on",
            "domain": "switch",
        },
        {
            "entity_id": "light.lounge_strip_lights_left",
            "name": "Lounge Strip Lights Left",
            "state": "off",
            "domain": "light",
        },
        {
            "entity_id": "light.lounge_strip_lights_right",
            "name": "Lounge Strip Lights Right",
            "state": "off",
            "domain": "light",
        },
        {
            "entity_id": "light.bar_lamp",
            "name": "Bar Lamp",
            "state": "off",
            "domain": "light",
        },
        {
            "entity_id": "notify.mobile_app_iphone_13",
            "name": "Notify Iphone 13",
            "state": "service",
            "domain": "notify",
            "device_class": "service",
        },
    ]
    fake_client = MagicMock()
    fake_client._request_timeout = 420
    fake_client.complete = AsyncMock(
        return_value={
            "yaml": (
                "alias: Robot vacuum cleaning: weekday morning\n"
                "description: Every weekday morning: check if the robot vacuum has cleaned in the last 24 hours.\n"
                "triggers:\n"
                "  - trigger: time\n"
                "    at: 08:00:00\n"
                "    weekday:\n"
                "      - mon\n"
                "      - tue\n"
                "      - wed\n"
                "      - thu\n"
                "      - fri\n"
                "conditions:\n"
                "  - condition: state\n"
                "    entity_id: switch.router_led_left\n"
                '    state: "on"\n'
                "actions:\n"
                "  - action: vacuum.start\n"
                "    target:\n"
                "      entity_id: vacuum.robot_vacuum\n"
                "  - action: notify.mobile_app_iphone_13\n"
                "    data:\n"
                "      message: The robot vacuum is still cleaning after 90 minutes: it might be stuck\n"
                "mode: single\n"
            ),
            "summary": "Starts the robot vacuum if the conditions are met.",
            "needs_clarification": False,
            "clarifying_questions": [],
        }
    )

    with patch(
        "custom_components.automagic.api.get_entity_context",
        AsyncMock(return_value=entities),
    ), patch(
        "custom_components.automagic.api.build_prompt",
        return_value=[{"role": "user", "content": "prompt"}],
    ), patch(
        "custom_components.automagic.api.async_get_clientsession",
        return_value=MagicMock(),
    ), patch(
        "custom_components.automagic.api.LLMClient.from_config",
        return_value=fake_client,
    ):
        await _run_generation_job(
            hass,
            job["job_id"],
            prompt,
            None,
        )

    assert job["status"] == "completed"
    assert _validate_generated_yaml(job["yaml"]) is None
    assert 'alias: "Robot vacuum cleaning: weekday morning"' in job["yaml"]
    assert (
        'description: "Every weekday morning: check if the robot vacuum has cleaned in the last 24 hours."'
        in job["yaml"]
    )
    assert 'at: "08:00:00"' in job["yaml"]
    assert (
        'message: "The robot vacuum is still cleaning after 90 minutes: it might be stuck"'
        in job["yaml"]
    )


@pytest.mark.asyncio
async def test_run_generation_job_waits_for_clarification_when_yaml_missing():
    """Clarification responses should pause the job instead of completing it."""
    hass = _make_hass()
    job = _create_generation_job(hass, "Turn on the kitchen lights", ["light"])

    entities = [
        {"entity_id": "light.kitchen", "name": "Kitchen", "state": "off", "domain": "light"},
    ]
    fake_client = MagicMock()
    fake_client._request_timeout = 420
    fake_client.complete = AsyncMock(
        return_value={
            "yaml": None,
            "summary": "I need to know which light should flash.",
            "needs_clarification": True,
            "clarifying_questions": ["Which light should flash?"],
        }
    )

    with patch(
        "custom_components.automagic.api.get_entity_context",
        AsyncMock(return_value=entities),
    ), patch(
        "custom_components.automagic.api.build_prompt",
        return_value=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "prompt"},
        ],
    ), patch(
        "custom_components.automagic.api.async_get_clientsession",
        return_value=MagicMock(),
    ), patch(
        "custom_components.automagic.api.LLMClient.from_config",
        return_value=fake_client,
    ):
        await _run_generation_job(
            hass,
            job["job_id"],
            "Turn on the kitchen lights",
            ["light"],
        )

    assert job["status"] == "needs_clarification"
    assert job["yaml"] is None
    assert job["clarifying_questions"] == ["Which light should flash?"]
    assert job["conversation_messages"][-1]["role"] == "assistant"
    assert "Which light should flash?" in job["conversation_messages"][-1]["content"]


@pytest.mark.asyncio
async def test_run_generation_job_auto_resolves_grouped_sensor_clarification():
    """Grouped sensor questions should be auto-answered from the original prompt."""
    hass = _make_hass()
    job = _create_generation_job(
        hass,
        "Monitor all three AC output phases from the Victron",
        None,
    )

    entities = [
        {
            "entity_id": "sensor.victron_mk3_ac_output_voltage",
            "name": "AC Output Voltage",
            "state": "230",
            "domain": "sensor",
            "device_class": "voltage",
        },
        {
            "entity_id": "sensor.victron_mk3_ac_output_voltage_l2",
            "name": "AC Output Voltage L2",
            "state": "229",
            "domain": "sensor",
            "device_class": "voltage",
        },
        {
            "entity_id": "sensor.victron_mk3_ac_output_voltage_l3",
            "name": "AC Output Voltage L3",
            "state": "228",
            "domain": "sensor",
            "device_class": "voltage",
        },
    ]
    fake_client = MagicMock()
    fake_client._request_timeout = 420
    fake_client.complete = AsyncMock(
        side_effect=[
            {
                "yaml": None,
                "summary": "Need a specific voltage sensor.",
                "needs_clarification": True,
                "clarifying_questions": [
                    "Which sensor should I use for AC Output Voltage? (sensor.victron_mk3_ac_output_voltage or sensor.victron_mk3_ac_output_voltage_l2 or sensor.victron_mk3_ac_output_voltage_l3)"
                ],
            },
            {
                "yaml": "alias: Victron Alert\ntriggers:\n  - trigger: template\nactions:\n  - action: notify.mobile_app_iphone_13",
                "summary": "Warns on phase imbalance.",
                "needs_clarification": False,
                "clarifying_questions": [],
            },
        ]
    )

    with patch(
        "custom_components.automagic.api.get_entity_context",
        AsyncMock(return_value=entities),
    ), patch(
        "custom_components.automagic.api.async_get_clientsession",
        return_value=MagicMock(),
    ), patch(
        "custom_components.automagic.api.LLMClient.from_config",
        return_value=fake_client,
    ):
        await _run_generation_job(
            hass,
            job["job_id"],
            (
                "Monitor all three AC output phases from the Victron. "
                "If any single phase voltage drops below 210 volts, notify me."
            ),
            None,
        )

    assert job["status"] == "completed"
    assert "alias: Victron Alert" in job["yaml"]
    second_call_messages = fake_client.complete.await_args_list[1].args[0]
    assert second_call_messages[-1]["role"] == "user"
    assert "Use all matching entities in these sibling sets together" in second_call_messages[-1]["content"]


@pytest.mark.asyncio
async def test_run_generation_job_reasserts_resolved_clarification_once():
    """A repeated clarification should get one stronger auto-follow-up before surfacing."""
    hass = _make_hass()
    job = _create_generation_job(
        hass,
        "Monitor all three AC output phases from the Victron",
        None,
    )

    entities = [
        {
            "entity_id": "sensor.victron_mk3_ac_output_voltage",
            "name": "AC Output Voltage",
            "state": "230",
            "domain": "sensor",
            "device_class": "voltage",
        },
        {
            "entity_id": "sensor.victron_mk3_ac_output_voltage_l2",
            "name": "AC Output Voltage L2",
            "state": "229",
            "domain": "sensor",
            "device_class": "voltage",
        },
        {
            "entity_id": "sensor.victron_mk3_ac_output_voltage_l3",
            "name": "AC Output Voltage L3",
            "state": "228",
            "domain": "sensor",
            "device_class": "voltage",
        },
        {
            "entity_id": "automation.electricity_balance_above_ps1",
            "name": "Electricity balance ABOVE £1",
            "state": "on",
            "domain": "automation",
            "device_class": None,
        },
    ]
    fake_client = MagicMock()
    fake_client._request_timeout = 420
    fake_client.complete = AsyncMock(
        side_effect=[
            {
                "yaml": None,
                "summary": "Need the specific phase sensors.",
                "needs_clarification": True,
                "clarifying_questions": [
                    "Which voltage sensors should I use for monitoring?"
                ],
            },
            {
                "yaml": None,
                "summary": "Still need the specific phase sensors.",
                "needs_clarification": True,
                "clarifying_questions": [
                    "Which voltage sensors should I use for monitoring?"
                ],
            },
            {
                "yaml": "alias: Victron Alert\ntriggers:\n  - trigger: template\nactions:\n  - action: notify.mobile_app_iphone_13",
                "summary": "Warns on phase imbalance.",
                "needs_clarification": False,
                "clarifying_questions": [],
            },
        ]
    )

    with patch(
        "custom_components.automagic.api.get_entity_context",
        AsyncMock(return_value=entities),
    ), patch(
        "custom_components.automagic.api.async_get_clientsession",
        return_value=MagicMock(),
    ), patch(
        "custom_components.automagic.api.LLMClient.from_config",
        return_value=fake_client,
    ):
        await _run_generation_job(
            hass,
            job["job_id"],
            (
                "Monitor all three AC output phases from the Victron. "
                "If any single phase voltage drops below 210 volts, notify me."
            ),
            None,
        )

    assert job["status"] == "completed"
    assert fake_client.complete.await_count == 3
    third_call_messages = fake_client.complete.await_args_list[2].args[0]
    assert third_call_messages[-1]["role"] == "user"
    assert "This clarification has already been answered" in third_call_messages[-1]["content"]


@pytest.mark.asyncio
async def test_run_generation_job_repairs_invalid_yaml_after_auto_clarification():
    """Auto-answered clarification retries should still repair broken yaml before completion."""
    hass = _make_hass()
    job = _create_generation_job(
        hass,
        "Monitor all three AC output phases from the Victron",
        None,
    )

    entities = [
        {
            "entity_id": "sensor.victron_mk3_ac_output_voltage",
            "name": "AC Output Voltage",
            "state": "230",
            "domain": "sensor",
            "device_class": "voltage",
        },
        {
            "entity_id": "sensor.victron_mk3_ac_output_voltage_l2",
            "name": "AC Output Voltage L2",
            "state": "229",
            "domain": "sensor",
            "device_class": "voltage",
        },
        {
            "entity_id": "sensor.victron_mk3_ac_output_voltage_l3",
            "name": "AC Output Voltage L3",
            "state": "228",
            "domain": "sensor",
            "device_class": "voltage",
        },
        {
            "entity_id": "notify.mobile_app_iphone_13",
            "name": "Notify Iphone 13",
            "state": "service",
            "domain": "notify",
            "device_class": "service",
        },
    ]
    fake_client = MagicMock()
    fake_client._request_timeout = 420
    fake_client.complete = AsyncMock(
        side_effect=[
            {
                "yaml": None,
                "summary": "Need a specific voltage sensor.",
                "needs_clarification": True,
                "clarifying_questions": [
                    "Which sensor should I use for AC Output Voltage? (sensor.victron_mk3_ac_output_voltage or sensor.victron_mk3_ac_output_voltage_l2 or sensor.victron_mk3_ac_output_voltage_l3)"
                ],
            },
            {
                "yaml": (
                    "alias: Victron Alert\n"
                    "description: Broken draft.\n"
                    "trigger:\n"
                    "  - platform: template\n"
                    "action:\n"
                    "  - service: notify.mobile_app_iphone_13\n"
                ),
                "summary": "Broken draft",
                "needs_clarification": False,
                "clarifying_questions": [],
            },
            {
                "yaml": (
                    "alias: Victron Alert\n"
                    "description: Warns on phase imbalance.\n"
                    "triggers:\n"
                    "  - trigger: template\n"
                    "conditions: []\n"
                    "actions:\n"
                    "  - action: notify.mobile_app_iphone_13\n"
                    "mode: single\n"
                ),
                "summary": "Warns on phase imbalance.",
                "needs_clarification": False,
                "clarifying_questions": [],
            },
        ]
    )

    with patch(
        "custom_components.automagic.api.get_entity_context",
        AsyncMock(return_value=entities),
    ), patch(
        "custom_components.automagic.api.async_get_clientsession",
        return_value=MagicMock(),
    ), patch(
        "custom_components.automagic.api.LLMClient.from_config",
        return_value=fake_client,
    ):
        await _run_generation_job(
            hass,
            job["job_id"],
            (
                "Monitor all three AC output phases from the Victron. "
                "If any single phase voltage drops below 210 volts, notify me."
            ),
            None,
        )

    assert job["status"] == "completed"
    assert "description: Warns on phase imbalance." in job["yaml"]
    assert fake_client.complete.await_count == 3
    repair_messages = fake_client.complete.await_args_list[2].args[0]
    assert repair_messages[-1]["role"] == "user"
    assert "Problems to fix:" in repair_messages[-1]["content"]


@pytest.mark.asyncio
async def test_run_generation_job_surfaces_llm_connection_errors():
    """LLM timeouts should be stored on the job for polling clients."""
    hass = _make_hass()
    job = _create_generation_job(hass, "Turn on the kitchen lights", None)

    fake_client = MagicMock()
    fake_client._request_timeout = 420
    fake_client.complete = AsyncMock(
        side_effect=LLMConnectionError("LLM request timed out after 420s")
    )

    with patch(
        "custom_components.automagic.api.get_entity_context",
        AsyncMock(
            return_value=[
                {"entity_id": "light.kitchen", "name": "Kitchen", "state": "off", "domain": "light"}
            ]
        ),
    ), patch(
        "custom_components.automagic.api.build_prompt",
        return_value=[{"role": "user", "content": "prompt"}],
    ), patch(
        "custom_components.automagic.api.async_get_clientsession",
        return_value=MagicMock(),
    ), patch(
        "custom_components.automagic.api.LLMClient.from_config",
        return_value=fake_client,
    ):
        await _run_generation_job(
            hass,
            job["job_id"],
            "Turn on the kitchen lights",
            None,
        )

    assert job["status"] == "error"
    assert "timed out after 420s" in job["error"]


@pytest.mark.asyncio
async def test_generate_status_view_returns_running_job_state():
    """Polling endpoint should report active jobs and backend status."""
    hass = _make_hass()
    job = _create_generation_job(hass, "Prompt", None)
    job["status"] = "running"
    job["message"] = "Waiting for your model to respond..."
    job["detail"] = "Still processing."
    job["started_at"] = job["updated_at"]
    job["started_monotonic"] = time.monotonic() - 75
    job["backend_status"] = {"message": "Ollama reports qwen2.5:14b is still running."}

    request = FakeRequest(hass, match_info={"job_id": job["job_id"]})
    view = AutoMagicGenerateStatusView()
    view.json = lambda data, status_code=200: {"status_code": status_code, **data}

    with patch(
        "custom_components.automagic.api._maybe_refresh_backend_status",
        AsyncMock(),
    ):
        result = await view.get(request, job["job_id"])

    assert result["status_code"] == 202
    assert result["status"] == "running"
    assert result["elapsed_seconds"] >= 75
    assert "still running" in result["backend_status"]["message"]


@pytest.mark.asyncio
async def test_generate_view_can_continue_after_clarification():
    """Follow-up answers should resume the same conversation thread."""
    hass = _make_hass()
    hass.async_create_task = MagicMock(return_value=MagicMock())

    parent_job = _create_generation_job(
        hass,
        "Turn on the kitchen lights",
        ["light"],
        conversation_messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "original prompt"},
            {"role": "assistant", "content": "Which light should flash?"},
        ],
        root_prompt="Turn on the kitchen lights",
    )
    parent_job["status"] = "needs_clarification"
    parent_job["clarifying_questions"] = ["Which light should flash?"]

    request = FakeRequest(
        hass,
        body={
            "prompt": "Use light.kitchen.",
            "continue_job_id": parent_job["job_id"],
        },
    )
    view = AutoMagicGenerateView()
    view.json = lambda data, status_code=200: {"status_code": status_code, **data}

    with patch(
        "custom_components.automagic.api._run_generation_job",
        AsyncMock(),
    ):
        result = await view.post(request)

    assert result["status_code"] == 202
    assert result["job_id"] != parent_job["job_id"]

    jobs = hass.data[f"{DOMAIN}_generation_jobs"]
    child_job = jobs[result["job_id"]]
    assert child_job["root_prompt"] == "Turn on the kitchen lights"
    assert child_job["conversation_messages"][-1] == {
        "role": "user",
        "content": "Use light.kitchen.",
    }


@pytest.mark.asyncio
async def test_generate_status_view_survives_backend_probe_failures():
    """Status polling should still work if the backend activity probe throws."""
    hass = _make_hass()
    job = _create_generation_job(hass, "Prompt", None)
    job["status"] = "running"
    job["message"] = "Waiting for your model to respond..."
    job["detail"] = "Still processing."
    job["started_at"] = job["updated_at"]
    job["started_monotonic"] = time.monotonic() - 30

    request = FakeRequest(hass, match_info={"job_id": job["job_id"]})
    view = AutoMagicGenerateStatusView()
    view.json = lambda data, status_code=200: {"status_code": status_code, **data}

    async def _explode(*_args, **_kwargs):
        raise RuntimeError("probe exploded")

    with patch(
        "custom_components.automagic.api._maybe_refresh_backend_status",
        _explode,
    ):
        result = await view.get(request, job["job_id"])

    assert result["status_code"] == 202
    assert result["status"] == "running"
    assert result["detail"] == "Still processing."
