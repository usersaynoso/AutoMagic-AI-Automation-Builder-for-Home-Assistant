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
    _INSTALL_REPAIR_SYSTEM_PROMPT,
    _YAML_REGENERATION_SYSTEM_PROMPT,
    _YAML_REPAIR_SYSTEM_PROMPT,
    _mark_job_complete,
    _extract_explicit_state_guards,
    _build_yaml_regeneration_messages,
    _build_yaml_repair_hints,
    _build_yaml_repair_messages,
    _collect_generated_yaml_issues,
    _create_generation_job,
    _extract_negated_state_guards,
    _extract_entity_ids_from_yaml,
    _find_hallucinated_entities,
    _get_config_data,
    _materialize_generation_result,
    _repair_generation_result,
    _regenerate_generation_result,
    _run_generation_job,
    _serialize_generation_job,
    _validate_generated_yaml,
    _yaml_guard_is_in_conditions_block,
    async_delete_history_entry_request,
    async_get_history_payload,
    async_get_services_payload,
    async_install_repair_request,
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
from custom_components.automagic.validation import ValidationReport


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


def test_mark_job_complete_sets_installable_flag_from_yaml_validation():
    """Completed jobs should persist whether the YAML is installable."""
    hass = _make_hass()
    job = _create_generation_job(hass, "Turn on the kitchen lights", None)

    _mark_job_complete(
        job,
        {
            "yaml": "alias: Broken\ndescription: bad: value: again\n",
            "summary": "Broken draft",
            "warnings": ["Invalid YAML: mapping values are not allowed here"],
        },
        [],
    )

    assert job["status"] == "completed"
    assert job["installable"] is False


def test_serialize_generation_job_includes_installable_for_completed_jobs():
    """Polling payloads should expose installability to the frontend."""
    hass = _make_hass()
    job = _create_generation_job(hass, "Turn on the kitchen lights", None)
    job["status"] = "completed"
    job["message"] = "Automation ready."
    job["detail"] = "Review the preview, then install when it looks correct."
    job["yaml"] = "alias: Example\ntriggers: []\nconditions: []\nactions: []\n"
    job["summary"] = "Example"
    job["warnings"] = []
    job["entities_used"] = []
    job["installable"] = False
    job["started_at"] = job["created_at"]
    job["started_monotonic"] = time.monotonic()
    job["finished_at"] = job["created_at"]
    job["finished_monotonic"] = job["started_monotonic"]

    payload = _serialize_generation_job(job)

    assert payload["status"] == "completed"
    assert payload["installable"] is False


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
    """Simple legacy YAML issues should be fixed without another LLM round-trip."""
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
    assert _validate_generated_yaml(job["yaml"]) is None
    assert "triggers:" in job["yaml"]
    assert "actions:" in job["yaml"]
    assert "action: light.turn_on" in job["yaml"]
    assert fake_client.complete.await_count == 1


@pytest.mark.asyncio
async def test_run_generation_job_regenerates_after_repair_attempts_stay_invalid():
    """Structural issues should first trigger a latest-draft repair attempt."""
    hass = _make_hass()
    job = _create_generation_job(
        hass,
        "Start the robot vacuum now. If it is still running after 2 hours, notify my phone.",
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
            "triggers:\n"
            "  - trigger: time\n"
            '    at: "08:00:00"\n'
            "conditions: []\n"
            "actions:\n"
            "  - action: vacuum.start\n"
            "    target:\n"
            "      entity_id: vacuum.robot_vacuum\n"
            '  - delay: "02:00:00"\n'
            "  - action: notify.mobile_app_phone\n"
            "    data:\n"
            '      message: "Still running"\n'
            "mode: single\n"
        ),
        "summary": "Broken draft",
        "needs_clarification": False,
        "clarifying_questions": [],
    }
    valid_yaml = {
        "yaml": (
            "alias: Robot Vacuum Check\n"
            "description: Waits for the vacuum to finish and notifies on timeout.\n"
            "triggers:\n"
            "  - trigger: time\n"
            '    at: "08:00:00"\n'
            "conditions: []\n"
            "actions:\n"
            "  - action: vacuum.start\n"
            "    target:\n"
            "      entity_id: vacuum.robot_vacuum\n"
            "  - wait_for_trigger:\n"
            "      - trigger: state\n"
            "        entity_id: vacuum.robot_vacuum\n"
            '        to: "docked"\n'
            '    timeout: "02:00:00"\n'
            "    continue_on_timeout: true\n"
            "  - choose:\n"
            "      - conditions:\n"
            "          - condition: template\n"
            '            value_template: "{{ not wait.completed }}"\n'
            "        sequence:\n"
            "          - action: notify.mobile_app_phone\n"
            "            data:\n"
            '              message: "Still running"\n'
            "mode: single\n"
        ),
        "summary": "Waits for the vacuum to finish and notifies on timeout.",
        "needs_clarification": False,
        "clarifying_questions": [],
    }
    fake_client = MagicMock()
    fake_client._request_timeout = 420
    fake_client.complete = AsyncMock(side_effect=[invalid_yaml, valid_yaml])

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
            "Start the robot vacuum now. If it is still running after 2 hours, notify my phone.",
            None,
        )

    assert job["status"] == "completed"
    assert _validate_generated_yaml(job["yaml"]) is None
    assert fake_client.complete.await_count == 2
    repair_messages = fake_client.complete.await_args_list[1].args[0]
    assert repair_messages[-1]["role"] == "user"
    assert "Correction attempt 1." in repair_messages[-1]["content"]
    assert "After a delay, re-check the relevant state before notifying" in repair_messages[-1]["content"]


@pytest.mark.asyncio
async def test_run_generation_job_keeps_retrying_beyond_previous_yaml_retry_cap():
    """The backend should keep retrying past the old single-regeneration limit."""
    hass = _make_hass()
    job = _create_generation_job(
        hass,
        "Start the robot vacuum now. If it is still running after 2 hours, notify my phone.",
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
            "triggers:\n"
            "  - trigger: time\n"
            '    at: "08:00:00"\n'
            "conditions: []\n"
            "actions:\n"
            "  - action: vacuum.start\n"
            "    target:\n"
            "      entity_id: vacuum.robot_vacuum\n"
            '  - delay: "02:00:00"\n'
            "  - action: notify.mobile_app_phone\n"
            "    data:\n"
            '      message: "Still running"\n'
            "mode: single\n"
        ),
        "summary": "Broken draft",
        "needs_clarification": False,
        "clarifying_questions": [],
    }
    fake_client = MagicMock()
    fake_client._request_timeout = 420
    fake_client.complete = AsyncMock(
        side_effect=[invalid_yaml, invalid_yaml, invalid_yaml, invalid_yaml]
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
            "Start the robot vacuum now. If it is still running after 2 hours, notify my phone.",
            None,
        )

    assert job["status"] == "completed"
    assert fake_client.complete.await_count == 4
    assert "After a delay, re-check the relevant state before notifying" in " ".join(job["warnings"])


@pytest.mark.asyncio
async def test_run_generation_job_sets_repair_in_progress_on_invalid_yaml():
    """Autofix should complete simple repairs without leaving repair state behind."""
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

    fake_client = MagicMock()
    fake_client._request_timeout = 420
    fake_client.complete = AsyncMock(side_effect=[invalid_yaml_response, valid_yaml_response])

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
    assert fake_client.complete.await_count == 1
    assert _validate_generated_yaml(job["yaml"]) is None


@pytest.mark.asyncio
async def test_run_generation_job_repair_failure_includes_helpful_detail():
    """If clean regeneration fails at the transport layer, the job should error clearly."""
    hass = _make_hass()
    job = _create_generation_job(
        hass,
        "Start the robot vacuum now. If it is still running after 2 hours, notify my phone.",
        None,
    )

    entities = [
        {"entity_id": "vacuum.robot_vacuum", "name": "Robot Vacuum", "state": "docked", "domain": "vacuum"},
        {"entity_id": "notify.mobile_app_phone", "name": "Phone", "state": "service", "domain": "notify"},
    ]
    invalid_yaml_response = {
        "yaml": (
            "alias: Robot Vacuum Check\n"
            "description: Broken draft.\n"
            "triggers:\n"
            "  - trigger: time\n"
            '    at: "08:00:00"\n'
            "conditions: []\n"
            "actions:\n"
            "  - action: vacuum.start\n"
            "    target:\n"
            "      entity_id: vacuum.robot_vacuum\n"
            '  - delay: "02:00:00"\n'
            "  - action: notify.mobile_app_phone\n"
            "    data:\n"
            '      message: "Still running"\n'
            "mode: single\n"
        ),
        "summary": "Broken draft",
        "needs_clarification": False,
        "clarifying_questions": [],
    }
    fake_client = MagicMock()
    fake_client._request_timeout = 420
    fake_client.complete = AsyncMock(
        side_effect=[invalid_yaml_response, LLMConnectionError("Timed out while contacting the AI service")]
    )

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
        await _run_generation_job(
            hass,
            job["job_id"],
            "Start the robot vacuum now. If it is still running after 2 hours, notify my phone.",
            None,
        )

    assert job["status"] == "error"
    assert not job.get("repair_in_progress")
    assert job.get("detail")
    assert "Timed out while contacting the AI service" in job["error"]


@pytest.mark.asyncio
async def test_run_generation_job_retries_with_specific_error_after_invalid_regeneration():
    """Legacy action: delay drafts should be autofixed without regeneration."""
    hass = _make_hass()
    job = _create_generation_job(hass, "Turn on the kitchen lights after five minutes", ["light"])

    entities = [
        {"entity_id": "light.kitchen", "name": "Kitchen", "state": "off", "domain": "light"},
    ]
    invalid_delay_yaml = {
        "yaml": (
            "alias: Kitchen Lights\n"
            "description: Broken delay draft.\n"
            "triggers:\n"
            "  - trigger: state\n"
            "    entity_id: light.kitchen\n"
            '    to: "on"\n'
            "conditions: []\n"
            "actions:\n"
            "  - action: delay\n"
            "    data:\n"
            '      duration: "00:05:00"\n'
            "  - action: light.turn_on\n"
            "    target:\n"
            "      entity_id: light.kitchen\n"
            "mode: single\n"
        ),
        "summary": "Broken delay draft",
        "needs_clarification": False,
        "clarifying_questions": [],
    }
    fake_client = MagicMock()
    fake_client._request_timeout = 420
    fake_client.complete = AsyncMock(return_value=invalid_delay_yaml)

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
            "Turn on the kitchen lights after five minutes",
            ["light"],
        )

    assert job["status"] == "completed"
    assert _validate_generated_yaml(job["yaml"]) is None
    assert "action: delay" not in job["yaml"]
    assert "delay:" in job["yaml"]
    assert fake_client.complete.await_count == 1


@pytest.mark.asyncio
async def test_run_generation_job_retries_clean_regeneration_after_response_parsing_failure():
    """Initial response parsing failures should trigger one clean regeneration pass."""
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
                "LLM response did not include automation YAML, intent JSON, or clarification questions"
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
    assert "Turns on the kitchen lights." in job["yaml"]
    assert fake_client.complete.await_count == 2
    regeneration_messages = fake_client.complete.await_args_list[1].args[0]
    assert regeneration_messages[-1]["role"] == "user"
    assert "Regenerate the automation from scratch. Ignore all previous drafts." in regeneration_messages[-1]["content"]


@pytest.mark.asyncio
async def test_run_generation_job_retries_after_repair_response_parsing_failure():
    """If the single clean regeneration response cannot be parsed, the job should error."""
    hass = _make_hass()
    job = _create_generation_job(
        hass,
        "Start the robot vacuum now. If it is still running after 2 hours, notify my phone.",
        None,
    )

    entities = [
        {"entity_id": "vacuum.robot_vacuum", "name": "Robot Vacuum", "state": "docked", "domain": "vacuum"},
        {"entity_id": "notify.mobile_app_phone", "name": "Phone", "state": "service", "domain": "notify"},
    ]
    invalid_yaml_response = {
        "yaml": (
            "alias: Robot Vacuum Check\n"
            "description: Broken draft.\n"
            "triggers:\n"
            "  - trigger: time\n"
            '    at: "08:00:00"\n'
            "conditions: []\n"
            "actions:\n"
            "  - action: vacuum.start\n"
            "    target:\n"
            "      entity_id: vacuum.robot_vacuum\n"
            '  - delay: "02:00:00"\n'
            "  - action: notify.mobile_app_phone\n"
            "    data:\n"
            '      message: "Still running"\n'
            "mode: single\n"
        ),
        "summary": "Broken draft",
        "needs_clarification": False,
        "clarifying_questions": [],
    }
    fake_client = MagicMock()
    fake_client._request_timeout = 420
    fake_client.complete = AsyncMock(
        side_effect=[
            invalid_yaml_response,
            LLMResponseError("Failed to parse LLM response as JSON"),
        ]
    )

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
        await _run_generation_job(
            hass,
            job["job_id"],
            "Start the robot vacuum now. If it is still running after 2 hours, notify my phone.",
            None,
        )

    assert job["status"] == "error"
    assert fake_client.complete.await_count == 2
    assert "Last issue: Failed to parse LLM response as JSON" in job["error"]


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
    assert "Robot vacuum cleaning: weekday morning" in job["yaml"]
    assert "Every weekday morning: check if the robot vacuum cleaned recently." in job["yaml"]
    assert "Warning: Robot vacuum might be stuck" in job["yaml"]


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
                "  - condition: state\n"
                "    entity_id: switch.router_led_right\n"
                '    state: "on"\n'
                "  - condition: not\n"
                "    conditions:\n"
                "      - condition: state\n"
                "        entity_id: sensor.iphone_13_audio_output\n"
                '        state: "Speaker"\n'
                "actions:\n"
                "  - action: vacuum.start\n"
                "    target:\n"
                "      entity_id: vacuum.robot_vacuum\n"
                "  - action: light.turn_on\n"
                "    target:\n"
                "      entity_id:\n"
                "        - light.lounge_strip_lights_left\n"
                "        - light.lounge_strip_lights_right\n"
                "        - light.bar_lamp\n"
                "    data:\n"
                "      brightness_pct: 20\n"
                "      kelvin: 2700\n"
                '  - delay: "01:30:00"\n'
                "  - action: notify.mobile_app_iphone_13\n"
                "    data:\n"
                "      message: The robot vacuum is still cleaning after 90 minutes: it might be stuck\n"
                "  - action: light.turn_off\n"
                "    target:\n"
                "      entity_id:\n"
                "        - light.lounge_strip_lights_left\n"
                "        - light.lounge_strip_lights_right\n"
                "        - light.bar_lamp\n"
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
    assert "Robot vacuum cleaning: weekday morning" in job["yaml"]
    assert "Every weekday morning: check if the robot vacuum has cleaned" in job["yaml"]
    assert "08:00:00" in job["yaml"]
    assert "The robot vacuum is still cleaning after 90 minutes: it might be stuck" in job["yaml"]


def test_collect_generated_yaml_issues_flags_semantic_mismatches_for_vacuum_prompt():
    """Prompt-aware backend validation should catch the reported weekday, guard, and color mistakes."""
    prompt = (
        "Every weekday morning, check if Janet (the robot vacuum) has done a clean in the last 24 hours. "
        "If she hasn't, start her cleaning at 8am, but only if everyone has already left home - check this "
        'by making sure the iPhone 13 audio output is not "Speaker" (meaning the phone is not actively being '
        "used at home). While Janet is cleaning, turn the lounge strip lights and bar lamp to a dim warm white "
        "at 20% brightness so she can see. When she finishes, turn those lights back off. If Janet doesn't "
        'finish within 90 minutes of starting, send a notification to my iPhone saying "Janet is still cleaning '
        'after 90 minutes - she might be stuck". Don\'t start her at all if either of the router LED switches '
        "are already off, as that means the network is down and her cloud connection won't work."
    )
    entities = [
        {
            "entity_id": "vacuum.robot_vacuum",
            "name": "Janet",
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
    yaml_text = (
        "alias: Start Janet Cleaning on Weekdays\n"
        "description: Every weekday morning, check if Janet has cleaned in the last 24 hours and start her cleaning if conditions are met.\n"
        "triggers:\n"
        "  - trigger: time\n"
        '    at: "08:00:00"\n'
        "conditions:\n"
        "  - condition: state\n"
        "    entity_id: sensor.iphone_13_audio_output\n"
        '    state: "Speaker"\n'
        "  - condition: state\n"
        "    entity_id: switch.router_led_left\n"
        '    state: "on"\n'
        "actions:\n"
        "  - action: automation.toggle_vacuum_to_clean_or_not\n"
        "  - action: light.turn_on\n"
        "    target:\n"
        "      entity_id: light.lounge_strip_lights_left\n"
        "    data:\n"
        "      brightness_pct: 20\n"
        '      color_name: "warm_white"\n'
        "  - action: notify.mobile_app_iphone_13\n"
        "    data:\n"
        '      message: "Janet is still cleaning after 90 minutes - she might be stuck"\n'
        "mode: single\n"
    )

    issues = _collect_generated_yaml_issues(prompt, entities, yaml_text)
    assert any("weekday schedule" in issue for issue in issues)
    assert any(
        "switch.router_led_right is missing entirely" in issue
        for issue in issues
    )
    assert any(
        "bar lamp: light.bar_lamp" in issue
        for issue in issues
    )
    assert any(
        "sensor.iphone_13_audio_output to not be 'Speaker'" in issue
        for issue in issues
    )
    assert any(
        "does not include an explicit off path" in issue
        for issue in issues
    )
    assert any(
        "Replace underscore-separated values like warm_white" in issue
        for issue in issues
    )


def test_collect_generated_yaml_issues_flags_nested_trigger_weekday_action_condition_and_kelvin():
    """Static YAML checks should catch new malformed structures even without entity context."""
    yaml_text = (
        "alias: Broken Example\n"
        "weekday:\n"
        "  - mon\n"
        "triggers:\n"
        "  - trigger:\n"
        "      platform: time\n"
        '      at: "08:00:00"\n'
        "actions:\n"
        "  - condition: state\n"
        "    entity_id: light.test\n"
        '    state: "on"\n'
        "  - action: light.turn_on\n"
        "    target:\n"
        "      entity_id: light.test\n"
        "    data:\n"
        "      color_temp: 2700\n"
        "mode: single\n"
    )

    issues = _collect_generated_yaml_issues("", [], yaml_text)

    assert (
        "'weekday:' is not a valid top-level automation key. Weekday restrictions must go inside a 'condition: time' block under conditions: or inside a trigger's 'at:' schedule."
        in issues
    )
    assert (
        "Trigger 0: 'trigger:' must be a plain string like 'trigger: time', not a nested mapping. Found 'trigger:' used as a block instead of a scalar."
        in issues
    )
    assert (
        "Action 0: bare 'condition:' inside actions: is not valid flow control. Use a 'choose:' block with a 'conditions:' list and 'sequence:' to branch, or move the condition to the top-level conditions: block."
        in issues
    )
    assert (
        "color_temp value 2700 looks like Kelvin. Convert it to mireds with round(1000000 / kelvin)."
        in issues
    )


def test_extract_explicit_state_guards_matches_either_router_led_switch_phrase():
    """The explicit guard extractor should resolve both router LED switches from 'either ... are already off'."""
    prompt = (
        "Don't start it at all if either of the router LED switches are already off, "
        "as that means the network is down."
    )
    entities = [
        {
            "entity_id": "switch.main_router_led",
            "name": "Main Router LED",
            "state": "on",
            "domain": "switch",
        },
        {
            "entity_id": "switch.mesh_mesh_led",
            "name": "Mesh Router LED",
            "state": "on",
            "domain": "switch",
        },
    ]

    guards = _extract_explicit_state_guards(prompt, entities)

    assert guards == [
        {
            "entity_id": "switch.main_router_led",
            "blocked_state": "off",
            "required_state": "on",
        },
        {
            "entity_id": "switch.mesh_mesh_led",
            "blocked_state": "off",
            "required_state": "on",
        },
    ]


def test_extract_negated_state_guards_matches_iphone_audio_output_phrase():
    """Prompt parsing should resolve the blocked iPhone audio-output state."""
    prompt = (
        "Start cleaning at 8am, making sure the iPhone 13 audio output is not "
        '"Speaker" before the vacuum runs.'
    )
    entities = [
        {
            "entity_id": "sensor.iphone_13_audio_output",
            "name": "iPhone 13 Audio Output",
            "state": "AirPlay",
            "domain": "sensor",
        }
    ]

    guards = _extract_negated_state_guards(prompt, entities)

    assert guards == [{"entity_id": "sensor.iphone_13_audio_output", "state": "Speaker"}]


def test_yaml_guard_is_in_conditions_block_only_matches_top_level_conditions():
    """Guard placement should only count when the entity is inside the top-level conditions block."""
    yaml_with_top_level_guard = (
        "alias: Router Guard\n"
        "description: Test\n"
        "triggers: []\n"
        "conditions:\n"
        "  - condition: state\n"
        "    entity_id: switch.main_router_led\n"
        '    state: "on"\n'
        "actions: []\n"
        "mode: single\n"
    )
    yaml_with_choose_guard = (
        "alias: Router Guard\n"
        "description: Test\n"
        "triggers: []\n"
        "conditions: []\n"
        "actions:\n"
        "  - choose:\n"
        "      - conditions:\n"
        "          - condition: state\n"
        "            entity_id: switch.main_router_led\n"
        '            state: "on"\n'
        "        sequence:\n"
        "          - action: light.turn_on\n"
        "            target:\n"
        "              entity_id: light.bar_lamp\n"
        "mode: single\n"
    )

    assert _yaml_guard_is_in_conditions_block(
        yaml_with_top_level_guard, "switch.main_router_led"
    )
    assert not _yaml_guard_is_in_conditions_block(
        yaml_with_choose_guard, "switch.main_router_led"
    )


def test_collect_generated_yaml_issues_flags_guards_nested_in_choose_branch():
    """Prompt-aware validation should reject explicit guards that only exist inside choose branches."""
    prompt = (
        "Don't start it at all if either of the router LED switches are already off, "
        "as that means the network is down."
    )
    entities = [
        {
            "entity_id": "switch.main_router_led",
            "name": "Main Router LED",
            "state": "on",
            "domain": "switch",
        },
        {
            "entity_id": "switch.mesh_mesh_led",
            "name": "Mesh Router LED",
            "state": "on",
            "domain": "switch",
        },
        {
            "entity_id": "light.bar_lamp",
            "name": "Bar Lamp",
            "state": "off",
            "domain": "light",
        },
    ]
    yaml_text = (
        "alias: Router Guard\n"
        "description: Test\n"
        "triggers:\n"
        "  - trigger: time\n"
        '    at: "08:00:00"\n'
        "conditions: []\n"
        "actions:\n"
        "  - choose:\n"
        "      - conditions:\n"
        "          - condition: state\n"
        "            entity_id: switch.main_router_led\n"
        '            state: "on"\n'
        "          - condition: state\n"
        "            entity_id: switch.mesh_mesh_led\n"
        '            state: "on"\n'
        "        sequence:\n"
        "          - action: light.turn_on\n"
        "            target:\n"
        "              entity_id: light.bar_lamp\n"
        "mode: single\n"
    )

    issues = _collect_generated_yaml_issues(prompt, entities, yaml_text)

    assert any(
        "Guard switch.main_router_led must be in the top-level conditions: block"
        in issue
        for issue in issues
    )
    assert any(
        "Guard switch.mesh_mesh_led must be in the top-level conditions: block"
        in issue
        for issue in issues
    )


def test_negated_state_guard_repairs_include_concrete_yaml_examples():
    """Repair hints and retry prompts should embed the exact blocked-state YAML shape."""
    issues = [
        (
            'Guard sensor.iphone_13_audio_output must NOT be "Speaker". '
            "Use a condition entry like: "
            '- condition: not / conditions: / - condition: state / entity_id: '
            'sensor.iphone_13_audio_output / state: "Speaker" or '
            '- condition: template / value_template: '
            '"{{ states(\'sensor.iphone_13_audio_output\') != \'Speaker\' }}"'
        )
    ]
    request_messages = [{"role": "user", "content": "prompt"}]
    result = {
        "yaml": "alias: Test\ndescription: Test\ntriggers: []\nconditions: []\nactions: []\nmode: single\n",
        "summary": "Test automation",
        "needs_clarification": False,
        "clarifying_questions": [],
    }

    hints = _build_yaml_repair_hints(issues)
    repair_messages = _build_yaml_repair_messages(
        request_messages,
        result,
        issues,
        attempt_number=2,
    )
    regeneration_messages = _build_yaml_regeneration_messages(
        request_messages,
        issues,
        attempt_number=3,
    )

    assert any(
        "For sensor.iphone_13_audio_output != \"Speaker\", use a condition entry like"
        in hint
        for hint in hints
    )
    assert any(
        'value_template: "{{ states(\'sensor.iphone_13_audio_output\') != \'Speaker\' }}"'
        in hint
        for hint in hints
    )
    assert "Concrete YAML examples for blocked-state guards:" in repair_messages[-1]["content"]
    assert "Use this condition entry:" in repair_messages[-1]["content"]
    assert "entity_id: sensor.iphone_13_audio_output" in repair_messages[-1]["content"]
    assert (
        'value_template: "{{ states(\'sensor.iphone_13_audio_output\') != \'Speaker\' }}"'
        in repair_messages[-1]["content"]
    )
    assert (
        "Concrete YAML examples for blocked-state guards:"
        in regeneration_messages[-1]["content"]
    )
    assert "entity_id: sensor.iphone_13_audio_output" in regeneration_messages[-1]["content"]
    assert (
        'value_template: "{{ states(\'sensor.iphone_13_audio_output\') != \'Speaker\' }}"'
        in regeneration_messages[-1]["content"]
    )


def test_yaml_repair_hints_include_concrete_examples_for_new_issue_types():
    """The repair user message should include concrete YAML snippets for each new issue type."""
    issues = [
        "Trigger 0: 'trigger:' must be a plain string like 'trigger: time', not a nested mapping. Found 'trigger:' used as a block instead of a scalar.",
        "'weekday:' is not a valid top-level automation key. Weekday restrictions must go inside a 'condition: time' block under conditions: or inside a trigger's 'at:' schedule.",
        "color_temp value 2700 looks like Kelvin. color_temp must be in mireds (153-500). Convert Kelvin to mireds with: mireds = round(1000000 / kelvin). For warm white 2700K use color_temp: 370, for 3000K use color_temp: 333.",
        "Action 0: bare 'condition:' inside actions: is not valid flow control. Use a 'choose:' block with a 'conditions:' list and 'sequence:' to branch, or move the condition to the top-level conditions: block.",
        "Preserve ALL resolved guard entities: switch.main_router_led, switch.mesh_mesh_led. The prompt said 'either' meaning both switches must be present as separate conditions.",
    ]
    request_messages = [{"role": "user", "content": "prompt"}]
    result = {
        "yaml": "alias: Test\ndescription: Test\ntriggers: []\nconditions: []\nactions: []\nmode: single\n",
        "summary": "Test automation",
        "needs_clarification": False,
        "clarifying_questions": [],
    }

    hints = _build_yaml_repair_hints(issues)
    repair_messages = _build_yaml_repair_messages(
        request_messages,
        result,
        issues,
        attempt_number=2,
    )

    assert any("Correct trigger syntax:" in hint for hint in hints)
    assert any("Weekday restrictions must be a condition: time block like this:" in hint for hint in hints)
    assert any("Use mired color_temp values like this:" in hint for hint in hints)
    assert any("Use choose for action-time branching like this:" in hint for hint in hints)
    assert any("Keep both guard switches as separate conditions like this:" in hint for hint in hints)
    assert "Correct trigger syntax:" in repair_messages[-1]["content"]
    assert "Weekday restrictions must be a condition: time block like this:" in repair_messages[-1]["content"]
    assert "Use mired color_temp values like this:" in repair_messages[-1]["content"]
    assert "Use choose for action-time branching like this:" in repair_messages[-1]["content"]
    assert "Keep both guard switches as separate conditions like this:" in repair_messages[-1]["content"]
    assert "entity_id: switch.main_router_led" in repair_messages[-1]["content"]
    assert "entity_id: switch.mesh_mesh_led" in repair_messages[-1]["content"]


def test_yaml_repair_hints_include_top_level_conditions_guard_example():
    """Repair hints should explain that blocking guards belong in top-level conditions."""
    hints = _build_yaml_repair_hints(
        [
            (
                "Guard switch.main_router_led must be in the top-level conditions: block, "
                "not inside a choose: branch. Automations that must not start when "
                "switch.main_router_led is off need this as an upfront blocking condition."
            )
        ]
    )

    assert any(
        "Guards that prevent the entire automation from running belong in conditions:, not in choose: branches:"
        in hint
        for hint in hints
    )
    assert any("entity_id: switch.main_router_led" in hint for hint in hints)
    assert any("entity_id: switch.mesh_mesh_led" in hint for hint in hints)


def test_collect_generated_yaml_issues_flags_missing_light_colour_and_brightness_data():
    """Prompt-aware validation should reject light.turn_on actions that omit requested colour data."""
    prompt = "When the front door opens, turn the bar lamp warm white at 20% brightness."
    entities = [
        {
            "entity_id": "binary_sensor.front_door",
            "name": "Front Door",
            "state": "off",
            "domain": "binary_sensor",
        },
        {
            "entity_id": "light.bar_lamp",
            "name": "Bar Lamp",
            "state": "off",
            "domain": "light",
        },
    ]
    yaml_text = (
        "alias: Bar Lamp Warm White\n"
        "description: Turn on the bar lamp when the front door opens.\n"
        "triggers:\n"
        "  - trigger: state\n"
        "    entity_id: binary_sensor.front_door\n"
        '    to: "on"\n'
        "conditions: []\n"
        "actions:\n"
        "  - action: light.turn_on\n"
        "    target:\n"
        "      entity_id: light.bar_lamp\n"
        "mode: single\n"
    )

    issues = _collect_generated_yaml_issues(prompt, entities, yaml_text)

    assert any(
        "Every affected light.turn_on action must include color_temp"
        in issue
        for issue in issues
    )


def test_collect_generated_yaml_issues_flags_unconditional_notify_after_delay():
    """Prompt-aware validation should require a choose block for delayed conditional notifications."""
    prompt = (
        "Start Janet cleaning now. If she hasn't finished after 90 minutes, send a "
        "notification to my iPhone."
    )
    entities = [
        {
            "entity_id": "vacuum.robot_vacuum",
            "name": "Janet",
            "state": "cleaning",
            "domain": "vacuum",
        },
        {
            "entity_id": "notify.mobile_app_iphone_13",
            "name": "Notify Iphone 13",
            "state": "service",
            "domain": "notify",
        },
    ]
    yaml_text = (
        "alias: Janet Delay Notify\n"
        "description: Notify after Janet is delayed.\n"
        "triggers:\n"
        "  - trigger: time\n"
        '    at: "08:00:00"\n'
        "conditions: []\n"
        "actions:\n"
        "  - action: vacuum.start\n"
        "    target:\n"
        "      entity_id: vacuum.robot_vacuum\n"
        '  - delay: "01:30:00"\n'
        "  - action: notify.mobile_app_iphone_13\n"
        "    data:\n"
        '      message: "Janet is still cleaning"\n'
        "mode: single\n"
    )

    issues = _collect_generated_yaml_issues(prompt, entities, yaml_text)

    assert (
        "After a delay, re-check the relevant state before notifying instead of sending an unconditional notification."
    ) in issues


def test_collect_generated_yaml_issues_flags_wait_for_trigger_without_timeout():
    """Prompt-aware validation should require timeout + wait.completed branching."""
    prompt = (
        "Start Janet cleaning now. Wait for her to finish, but if she hasn't finished "
        "after 2 hours, send a notification to my iPhone."
    )
    entities = [
        {
            "entity_id": "vacuum.robot_vacuum",
            "name": "Janet",
            "state": "cleaning",
            "domain": "vacuum",
        },
        {
            "entity_id": "notify.mobile_app_iphone_13",
            "name": "Notify Iphone 13",
            "state": "service",
            "domain": "notify",
        },
    ]
    yaml_text = (
        "alias: Janet Wait Without Timeout\n"
        "description: Wait for Janet to finish.\n"
        "triggers:\n"
        "  - trigger: time\n"
        '    at: "08:00:00"\n'
        "conditions: []\n"
        "actions:\n"
        "  - action: vacuum.start\n"
        "    target:\n"
        "      entity_id: vacuum.robot_vacuum\n"
        "  - wait_for_trigger:\n"
        "      - trigger: state\n"
        "        entity_id: vacuum.robot_vacuum\n"
        '        to: "docked"\n'
        "  - action: notify.mobile_app_iphone_13\n"
        "    data:\n"
        '      message: "Janet is still cleaning after 2 hours"\n'
        "mode: single\n"
    )

    issues = _collect_generated_yaml_issues(prompt, entities, yaml_text)

    assert (
        "The automation uses wait_for_trigger without a timeout. Add timeout plus continue_on_timeout: true and branch on wait.completed."
    ) in issues


def test_yaml_repair_hints_include_conditional_notification_example():
    """Repair hints should explain the choose block shape for delayed notify checks."""
    hints = _build_yaml_repair_hints(
        [
            "After a delay the prompt requires a conditional notification — notify only if a "
            "condition is still true. Wrap the notify action in a choose: block after the delay "
            "that re-checks the relevant entity state before sending the notification."
        ]
    )

    assert any(
        "After a delay, use choose: to re-check the relevant state before notifying."
        in hint
        for hint in hints
    )
    assert any("entity_id: <relevant_entity>" in hint for hint in hints)
    assert any("action: <notify_service>" in hint for hint in hints)


def test_yaml_repair_hints_include_wait_for_trigger_timeout_example():
    """Repair hints should explain the wait_for_trigger timeout shape."""
    hints = _build_yaml_repair_hints(
        [
            "The automation uses wait_for_trigger but no timeout is set. When the prompt "
            "requires a different action if the event does not occur within a time limit, "
            "add 'timeout: HH:MM:SS' and 'continue_on_timeout: true' to the wait_for_trigger "
            "step, then use a choose: block branching on '{{ wait.completed }}' to handle "
            "both the event-occurred (true) and timed-out (false) cases."
        ]
    )

    assert any("continue_on_timeout: true" in hint for hint in hints)
    assert any("{{ not wait.completed }}" in hint for hint in hints)
    assert any("action: <service_for_normal_finish>" in hint for hint in hints)


def test_yaml_repair_hints_require_colour_persistence_across_repairs():
    """Repair hints should explicitly require copying prior light colour data forward."""
    hints = _build_yaml_repair_hints(
        [
            "The prompt requests a specific colour or brightness for lights, but no "
            "light.turn_on action includes colour or brightness data."
        ]
    )

    assert any(
        "MANDATORY: Copy colour and brightness data from the previous draft" in hint
        for hint in hints
    )
    assert any("Do not drop data: blocks from light.turn_on actions." in hint for hint in hints)


def test_yaml_regeneration_messages_discard_prior_assistant_turns():
    """Regeneration should start from system/user context only, without prior drafts."""
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "original request"},
        {"role": "assistant", "content": "broken draft"},
        {"role": "user", "content": "follow-up detail"},
    ]

    regeneration_messages = _build_yaml_regeneration_messages(
        messages,
        ["Invalid YAML"],
        attempt_number=2,
    )

    assert not any(message["role"] == "assistant" for message in regeneration_messages)
    assert not any(
        message["content"] == "broken draft" for message in regeneration_messages
    )
    assert any(
        message["content"] == "original request" for message in regeneration_messages
    )
    assert any(
        message["content"] == "follow-up detail" for message in regeneration_messages
    )


def test_repair_prompts_require_light_colour_and_brightness_data():
    """Repair-oriented backend prompts should preserve colour data and timeout branching guidance."""
    for prompt in (
        _YAML_REPAIR_SYSTEM_PROMPT,
        _YAML_REGENERATION_SYSTEM_PROMPT,
        _INSTALL_REPAIR_SYSTEM_PROMPT,
    ):
        assert "COLOUR PERSISTENCE RULE (mandatory)" in prompt
        assert "you MUST copy those exact values into the" in prompt
        assert "corrected draft" in prompt
        assert "color_temp: 370" in prompt
        assert "use wait_for_trigger with a timeout" in prompt
        assert "continue_on_timeout: true" in prompt
        assert "{{ wait.completed }}" in prompt


@pytest.mark.asyncio
async def test_regenerate_generation_result_caps_rounds_and_marks_job_error():
    """The standalone regeneration helper now performs one constrained retry."""
    fake_client = MagicMock()
    fake_client.complete = AsyncMock(side_effect=LLMResponseError("bad response"))

    with pytest.raises(LLMResponseError, match="bad response"):
        await _regenerate_generation_result(
            fake_client,
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "Turn on the kitchen lights"},
            ],
            "Turn on the kitchen lights",
            [],
            "Initial response was invalid",
        )

    assert fake_client.complete.await_count == 1


@pytest.mark.asyncio
async def test_materialize_generation_result_best_effort_assembles_yaml_for_invalid_intent():
    """Intent validation issues should not block deterministic YAML assembly."""
    fake_client = MagicMock()
    fake_client.complete = AsyncMock()
    intent = {
        "alias": "Kitchen Lights",
        "description": "Turns on the kitchen lights.",
        "triggers": [],
        "conditions": [],
        "actions": [],
        "mode": "single",
    }

    with patch(
        "custom_components.automagic.api.build_entity_resolution_map",
        return_value={},
    ), patch(
        "custom_components.automagic.api.validate_intent",
        return_value=(False, ["Mode should be reviewed."]),
    ), patch(
        "custom_components.automagic.api._intent_entity_issues",
        return_value=["Entity resolution was partial."],
    ), patch(
        "custom_components.automagic.api.assemble_yaml",
        return_value=(
            "alias: Kitchen Lights\n"
            "description: Turns on the kitchen lights.\n"
            "triggers: []\n"
            "conditions: []\n"
            "actions: []\n"
            "mode: single\n"
        ),
    ):
        result = await _materialize_generation_result(
            fake_client,
            [],
            "Turn on the kitchen lights",
            [],
            {"intent": intent, "summary": "Turns on the kitchen lights."},
            allow_intent_repair=False,
        )

    assert result["intent"] == intent
    assert result["yaml"].startswith("alias: Kitchen Lights")
    assert result["warnings"] == [
        "Mode should be reviewed.",
        "Entity resolution was partial.",
    ]
    assert fake_client.complete.await_count == 0


@pytest.mark.asyncio
async def test_repair_generation_result_regenerates_when_used_llm_repair_has_empty_yaml():
    """An empty YAML draft should still trigger clean regeneration even after intent repair."""
    fake_client = MagicMock()
    request_messages = [{"role": "user", "content": "Turn on the kitchen lights"}]
    regenerated = {
        "yaml": (
            "alias: Kitchen Lights\n"
            "description: Turns on the kitchen lights.\n"
            "triggers: []\n"
            "conditions: []\n"
            "actions: []\n"
            "mode: single\n"
        ),
        "summary": "Turns on the kitchen lights.",
        "warnings": [],
    }
    blocking_report = ValidationReport(
        syntax_errors=["The response did not include automation YAML."]
    )
    clean_report = ValidationReport()

    with patch(
        "custom_components.automagic.api._materialize_generation_result",
        AsyncMock(
            side_effect=[
                {
                    "yaml": "",
                    "summary": "Intent repair failed to assemble YAML.",
                    "warnings": [],
                    "used_llm_repair": True,
                },
                regenerated,
            ]
        ),
    ) as materialize_mock, patch(
        "custom_components.automagic.api.build_entity_resolution_map",
        return_value={},
    ), patch(
        "custom_components.automagic.api.validate_generated_yaml",
        side_effect=[blocking_report, clean_report],
    ), patch(
        "custom_components.automagic.api._build_deterministic_generation_result",
        return_value=None,
    ), patch(
        "custom_components.automagic.api.autofix_yaml",
        side_effect=[("", []), (regenerated["yaml"], [])],
    ), patch(
        "custom_components.automagic.api._single_clean_regeneration",
        AsyncMock(return_value={"intent": {"alias": "Kitchen Lights"}}),
    ) as regeneration_mock:
        result = await _repair_generation_result(
            fake_client,
            request_messages,
            "Turn on the kitchen lights",
            [],
            {"intent": {"alias": "Kitchen Lights"}},
        )

    assert regeneration_mock.await_count == 1
    assert materialize_mock.await_count == 2
    assert result["yaml"].startswith("alias: Kitchen Lights")
    assert result["summary"] == "Turns on the kitchen lights."


@pytest.mark.asyncio
async def test_repair_generation_result_marks_invalid_yaml_as_not_installable():
    """Unrepairable YAML should still return with installable=False for the UI gate."""
    fake_client = MagicMock()
    blocking_report = ValidationReport(
        syntax_errors=["Invalid YAML: mapping values are not allowed here"]
    )
    invalid_yaml = "alias: Broken\ndescription: bad: value: again\n"

    with patch(
        "custom_components.automagic.api._materialize_generation_result",
        AsyncMock(
            return_value={
                "yaml": invalid_yaml,
                "summary": "Broken draft",
                "warnings": [],
                "used_llm_repair": True,
            }
        ),
    ), patch(
        "custom_components.automagic.api.build_entity_resolution_map",
        return_value={},
    ), patch(
        "custom_components.automagic.api.validate_generated_yaml",
        side_effect=[
            blocking_report,
            blocking_report,
            blocking_report,
            blocking_report,
        ],
    ), patch(
        "custom_components.automagic.api._build_deterministic_generation_result",
        return_value=None,
    ), patch(
        "custom_components.automagic.api.autofix_yaml",
        return_value=(invalid_yaml, []),
    ), patch(
        "custom_components.automagic.api._request_yaml_repair_result",
        AsyncMock(
            return_value={
                "yaml": invalid_yaml,
                "summary": "Broken draft",
                "warnings": [],
                "used_llm_repair": True,
            }
        ),
    ), patch(
        "custom_components.automagic.api._regenerate_generation_result",
        AsyncMock(
            return_value={
                "yaml": invalid_yaml,
                "summary": "Broken draft",
                "warnings": [],
                "used_llm_repair": True,
            }
        ),
    ):
        result = await _repair_generation_result(
            fake_client,
            [{"role": "user", "content": "Turn on the kitchen lights"}],
            "Turn on the kitchen lights",
            [],
            {"yaml": invalid_yaml},
        )

    assert result["yaml"] == invalid_yaml
    assert result["installable"] is False
    assert "Invalid YAML" in result["warnings"][0]


@pytest.mark.asyncio
async def test_run_generation_job_repairs_prompt_coverage_issues_before_completion():
    """Prompt-coverage issues should keep retrying until a valid draft is produced."""
    hass = _make_hass()
    prompt = (
        "Every weekday morning, check if Janet (the robot vacuum) has done a clean in the last 24 hours. "
        "If she hasn't, start her cleaning at 8am, but only if everyone has already left home - check this "
        'by making sure the iPhone 13 audio output is not "Speaker" (meaning the phone is not actively being '
        "used at home). While Janet is cleaning, turn the lounge strip lights and bar lamp to a dim warm white "
        "at 20% brightness so she can see. When she finishes, turn those lights back off. If Janet doesn't "
        'finish within 90 minutes of starting, send a notification to my iPhone saying "Janet is still cleaning '
        'after 90 minutes - she might be stuck". Don\'t start her at all if either of the router LED switches '
        "are already off, as that means the network is down and her cloud connection won't work."
    )
    job = _create_generation_job(hass, prompt, None)

    entities = [
        {
            "entity_id": "vacuum.robot_vacuum",
            "name": "Janet",
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
    bad_yaml = {
        "yaml": (
            "alias: Start Janet Cleaning on Weekdays\n"
            "description: Every weekday morning, check if Janet has cleaned in the last 24 hours and start her cleaning if conditions are met.\n"
            "triggers:\n"
            "  - trigger: time\n"
            '    at: "08:00:00"\n'
            "conditions:\n"
            "  - condition: state\n"
            "    entity_id: sensor.iphone_13_audio_output\n"
            '    state: "Speaker"\n'
            "  - condition: state\n"
            "    entity_id: switch.router_led_left\n"
            '    state: "on"\n'
            "actions:\n"
            "  - action: automation.toggle_vacuum_to_clean_or_not\n"
            "  - action: light.turn_on\n"
            "    target:\n"
            "      entity_id: light.lounge_strip_lights_left\n"
            "    data:\n"
            "      brightness_pct: 20\n"
            '      color_name: "warm_white"\n'
            "  - action: notify.mobile_app_iphone_13\n"
            "    data:\n"
            '      message: "Janet is still cleaning after 90 minutes - she might be stuck"\n'
            "mode: single\n"
        ),
        "summary": "Starts Janet cleaning if the conditions are met.",
        "needs_clarification": False,
        "clarifying_questions": [],
    }
    fixed_yaml = {
        "yaml": (
            "alias: Start Janet Cleaning on Weekdays\n"
            'description: "Starts Janet cleaning at 08:00 on weekdays when the requested guards pass."\n'
            "triggers:\n"
            "  - trigger: time\n"
            '    at: "08:00:00"\n'
            "conditions:\n"
            "  - condition: state\n"
            "    entity_id: switch.router_led_left\n"
            '    state: "on"\n'
            "  - condition: state\n"
            "    entity_id: switch.router_led_right\n"
            '    state: "on"\n'
            "  - condition: not\n"
            "    conditions:\n"
            "      - condition: state\n"
            "        entity_id: sensor.iphone_13_audio_output\n"
            '        state: "Speaker"\n'
            "actions:\n"
            "  - action: vacuum.start\n"
            "    target:\n"
            "      entity_id: vacuum.robot_vacuum\n"
            "  - action: light.turn_on\n"
            "    target:\n"
            "      entity_id: [light.lounge_strip_lights_left, light.lounge_strip_lights_right, light.bar_lamp]\n"
            "    data:\n"
            "      brightness_pct: 20\n"
            "      color_temp: 370\n"
            "  - wait_for_trigger:\n"
            "      - trigger: state\n"
            "        entity_id: vacuum.robot_vacuum\n"
            '        to: "docked"\n'
            '    timeout: "01:30:00"\n'
            "    continue_on_timeout: true\n"
            "  - choose:\n"
            "      - conditions:\n"
            "          - condition: template\n"
            '            value_template: "{{ not wait.completed }}"\n'
            "        sequence:\n"
            "          - action: notify.mobile_app_iphone_13\n"
            "            data:\n"
            '              message: "Janet is still cleaning after 90 minutes - she might be stuck"\n'
            "  - action: light.turn_off\n"
            "    target:\n"
            "      entity_id: [light.lounge_strip_lights_left, light.lounge_strip_lights_right, light.bar_lamp]\n"
            "mode: single\n"
        ),
        "summary": "Starts Janet cleaning on weekdays when the requested guards pass.",
        "needs_clarification": False,
        "clarifying_questions": [],
    }
    completed_yaml = {
        "yaml": (
            "alias: Start Janet Cleaning on Weekdays\n"
            'description: "Starts Janet cleaning at 08:00 on weekdays when the requested guards pass."\n'
            "triggers:\n"
            "  - trigger: time\n"
            '    at: "08:00:00"\n'
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
            "  - condition: state\n"
            "    entity_id: switch.router_led_right\n"
            '    state: "on"\n'
            "  - condition: not\n"
            "    conditions:\n"
            "      - condition: state\n"
            "        entity_id: sensor.iphone_13_audio_output\n"
            '        state: "Speaker"\n'
            "actions:\n"
            "  - action: vacuum.start\n"
            "    target:\n"
            "      entity_id: vacuum.robot_vacuum\n"
            "  - action: light.turn_on\n"
            "    target:\n"
            "      entity_id: [light.lounge_strip_lights_left, light.lounge_strip_lights_right, light.bar_lamp]\n"
            "    data:\n"
            "      brightness_pct: 20\n"
            "      color_temp: 370\n"
            "  - wait_for_trigger:\n"
            "      - trigger: state\n"
            "        entity_id: vacuum.robot_vacuum\n"
            '        to: "docked"\n'
            '    timeout: "01:30:00"\n'
            "    continue_on_timeout: true\n"
            "  - choose:\n"
            "      - conditions:\n"
            "          - condition: template\n"
            '            value_template: "{{ not wait.completed }}"\n'
            "        sequence:\n"
            "          - action: notify.mobile_app_iphone_13\n"
            "            data:\n"
            '              message: "Janet is still cleaning after 90 minutes - she might be stuck"\n'
            "  - action: light.turn_off\n"
            "    target:\n"
            "      entity_id: [light.lounge_strip_lights_left, light.lounge_strip_lights_right, light.bar_lamp]\n"
            "mode: single\n"
        ),
        "summary": "Starts Janet cleaning on weekdays when the requested guards pass.",
        "needs_clarification": False,
        "clarifying_questions": [],
    }
    fake_client = MagicMock()
    fake_client._request_timeout = 420
    fake_client.complete = AsyncMock(side_effect=[bad_yaml, fixed_yaml, completed_yaml])

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
    assert '        state: "Speaker"' in job["yaml"]
    assert "vacuum.robot_vacuum" in job["yaml"]
    assert "switch.router_led_right" in job["yaml"]
    assert "color_temp: 370" in job["yaml"]
    assert fake_client.complete.await_count == 3
    repair_messages = fake_client.complete.await_args_list[1].args[0]
    assert repair_messages[-1]["role"] == "user"
    assert "Correction attempt 1." in repair_messages[-1]["content"]
    assert any(
        token in repair_messages[-1]["content"]
        for token in ("switch.router_led_right", "Speaker", "warm_white")
    )
    regeneration_messages = fake_client.complete.await_args_list[2].args[0]
    assert regeneration_messages[-1]["role"] == "user"
    assert "CONSTRAINTS:" in regeneration_messages[-1]["content"]
    assert "weekday schedule" in regeneration_messages[-1]["content"]


@pytest.mark.asyncio
async def test_run_generation_job_keeps_repairing_after_an_invalid_regeneration():
    """An invalid regeneration should trigger one more latest-draft repair attempt."""
    hass = _make_hass()
    prompt = (
        "Every weekday morning, check if Janet (the robot vacuum) has done a clean in the last 24 hours. "
        "If she hasn't, start her cleaning at 8am, but only if everyone has already left home - check this "
        'by making sure the iPhone 13 audio output is not "Speaker" (meaning the phone is not actively being '
        "used at home). While Janet is cleaning, turn the lounge strip lights and bar lamp to a dim warm white "
        "at 20% brightness so she can see. When she finishes, turn those lights back off. If Janet doesn't "
        'finish within 90 minutes of starting, send a notification to my iPhone saying "Janet is still cleaning '
        'after 90 minutes - she might be stuck". Don\'t start her at all if either of the router LED switches '
        "are already off, as that means the network is down and her cloud connection won't work."
    )
    job = _create_generation_job(hass, prompt, None)

    entities = [
        {
            "entity_id": "vacuum.robot_vacuum",
            "name": "Janet",
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
    initial_invalid_yaml = {
        "yaml": (
            "alias: Start Janet Cleaning on Weekdays\n"
            "description: Starts Janet cleaning when conditions are met.\n"
            "triggers:\n"
            "  - trigger: time\n"
            '    at: "08:00:00"\n'
            "conditions:\n"
            "  - condition: state\n"
            "    entity_id: switch.router_led_left\n"
            '    state: "on"\n'
            "actions:\n"
            "  - action: vacuum.robot_vacuum.start\n"
            "  - action: light.lounge_strip_lights_left.turn_on\n"
            "  - action: notify.mobile_app_iphone_13\n"
            "    data:\n"
            '      message: "Janet is still cleaning after 90 minutes - she might be stuck"\n'
            "mode: single\n"
        ),
        "summary": "Starts Janet cleaning.",
        "needs_clarification": False,
        "clarifying_questions": [],
    }
    partially_fixed_yaml = {
        "yaml": (
            "alias: Start Janet Cleaning on Weekdays\n"
            "description: Starts Janet cleaning when conditions are met.\n"
            "triggers:\n"
            "  - trigger: time\n"
            '    at: "08:00:00"\n'
            "conditions:\n"
            "  - condition: state\n"
            "    entity_id: switch.router_led_left\n"
            '    state: "on"\n'
            "actions:\n"
            "  - action: vacuum.start\n"
            "    target:\n"
            "      entity_id: vacuum.robot_vacuum\n"
            "  - action: light.turn_on\n"
            "    target:\n"
            "      entity_id: [light.lounge_strip_lights_left, light.lounge_strip_lights_right, light.bar_lamp]\n"
            "    data:\n"
            "      brightness_pct: 20\n"
            "      kelvin: 2700\n"
            '  - delay: "01:30:00"\n'
            "  - action: notify.mobile_app_iphone_13\n"
            "    data:\n"
            '      message: "Janet is still cleaning after 90 minutes - she might be stuck"\n'
            "mode: single\n"
        ),
        "summary": "Starts Janet cleaning when conditions are met.",
        "needs_clarification": False,
        "clarifying_questions": [],
    }
    still_incomplete_yaml = {
        "yaml": (
            "alias: Start Janet Cleaning on Weekdays\n"
            "description: Starts Janet cleaning when conditions are met.\n"
            "triggers:\n"
            "  - trigger: time\n"
            '    at: "08:00:00"\n'
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
            "  - action: light.turn_on\n"
            "    target:\n"
            "      entity_id: [light.lounge_strip_lights_left, light.lounge_strip_lights_right, light.bar_lamp]\n"
            "    data:\n"
            "      brightness_pct: 20\n"
            "      kelvin: 2700\n"
            '  - delay: "01:30:00"\n'
            "  - action: notify.mobile_app_iphone_13\n"
            "    data:\n"
            '      message: "Janet is still cleaning after 90 minutes - she might be stuck"\n'
            "mode: single\n"
        ),
        "summary": "Starts Janet cleaning on weekdays.",
        "needs_clarification": False,
        "clarifying_questions": [],
    }
    final_repaired_yaml = {
        "yaml": (
            "alias: Start Janet Cleaning on Weekdays\n"
            "description: Starts Janet cleaning when conditions are met.\n"
            "triggers:\n"
            "  - trigger: time\n"
            '    at: "08:00:00"\n'
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
            "  - condition: state\n"
            "    entity_id: switch.router_led_right\n"
            '    state: "on"\n'
            "  - condition: not\n"
            "    conditions:\n"
            "      - condition: state\n"
            "        entity_id: sensor.iphone_13_audio_output\n"
            '        state: "Speaker"\n'
            "actions:\n"
            "  - action: vacuum.start\n"
            "    target:\n"
            "      entity_id: vacuum.robot_vacuum\n"
            "  - action: light.turn_on\n"
            "    target:\n"
            "      entity_id: [light.lounge_strip_lights_left, light.lounge_strip_lights_right, light.bar_lamp]\n"
            "    data:\n"
            "      brightness_pct: 20\n"
            "      kelvin: 2700\n"
            "  - wait_for_trigger:\n"
            "      - trigger: state\n"
            "        entity_id: vacuum.robot_vacuum\n"
            '        to: "docked"\n'
            '    timeout: "01:30:00"\n'
            "    continue_on_timeout: true\n"
            "  - choose:\n"
            "      - conditions:\n"
            "          - condition: template\n"
            '            value_template: "{{ not wait.completed }}"\n'
            "        sequence:\n"
            "          - action: notify.mobile_app_iphone_13\n"
            "            data:\n"
            '              message: "Janet is still cleaning after 90 minutes - she might be stuck"\n'
            "  - action: light.turn_off\n"
            "    target:\n"
            "      entity_id: [light.lounge_strip_lights_left, light.lounge_strip_lights_right, light.bar_lamp]\n"
            "mode: single\n"
        ),
        "summary": "Starts Janet cleaning on weekdays.",
        "needs_clarification": False,
        "clarifying_questions": [],
    }
    fake_client = MagicMock()
    fake_client._request_timeout = 420
    fake_client.complete = AsyncMock(
        side_effect=[
            initial_invalid_yaml,
            partially_fixed_yaml,
            still_incomplete_yaml,
            final_repaired_yaml,
        ]
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
    assert fake_client.complete.await_count == 4
    assert _validate_generated_yaml(job["yaml"]) is None
    post_regen_repair_messages = fake_client.complete.await_args_list[3].args[0]
    assert post_regen_repair_messages[-1]["role"] == "user"
    assert "Correction attempt 1." in post_regen_repair_messages[-1]["content"]


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
    """Auto-answered clarifications should still allow autofix to finish the job."""
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
    assert "description: Broken draft." in job["yaml"] or 'description: "Broken draft."' in job["yaml"]
    assert "triggers:" in job["yaml"]
    assert "actions:" in job["yaml"]
    assert fake_client.complete.await_count == 2


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
async def test_generate_view_can_continue_after_completed_yaml_preview():
    """Follow-up change requests should resume the completed YAML thread with the prior automation context."""
    hass = _make_hass()
    hass.async_create_task = MagicMock(return_value=MagicMock())

    parent_job = _create_generation_job(
        hass,
        "Turn on the kitchen lights at 10am every day",
        ["light"],
        conversation_messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "Turn on the kitchen lights at 10am every day"},
        ],
        root_prompt="Turn on the kitchen lights at 10am every day",
    )
    parent_job["status"] = "completed"
    parent_job["yaml"] = (
        "alias: Kitchen Lights\n"
        "description: Turns on the kitchen lights at 10:00 every day.\n"
        "triggers:\n"
        "  - trigger: time\n"
        '    at: "10:00:00"\n'
        "conditions: []\n"
        "actions:\n"
        "  - action: light.turn_on\n"
        "    target:\n"
        "      entity_id: light.kitchen\n"
        "mode: single\n"
    )
    parent_job["summary"] = "Turns on the kitchen lights at 10:00 every day."

    request = FakeRequest(
        hass,
        body={
            "prompt": "Change it to 11am instead.",
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
    jobs = hass.data[f"{DOMAIN}_generation_jobs"]
    child_job = jobs[result["job_id"]]
    assert child_job["root_prompt"] == "Turn on the kitchen lights at 10am every day"
    assert child_job["conversation_messages"][-2]["role"] == "assistant"
    assert "Current automation YAML:" in child_job["conversation_messages"][-2]["content"]
    assert 'at: "10:00:00"' in child_job["conversation_messages"][-2]["content"]
    assert child_job["conversation_messages"][-1] == {
        "role": "user",
        "content": "Change it to 11am instead.",
    }


@pytest.mark.asyncio
async def test_run_generation_job_skips_deterministic_shortcut_for_follow_up_threads():
    """Follow-up threads should use the stored conversation context instead of regenerating from the original prompt."""
    hass = _make_hass()
    job = _create_generation_job(
        hass,
        "Turn on the kitchen lights at 10am every day",
        ["light"],
        conversation_messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "Turn on the kitchen lights at 10am every day"},
            {
                "role": "assistant",
                "content": (
                    "Summary:\nTurns on the kitchen lights at 10:00 every day.\n\n"
                    "Current automation YAML:\n"
                    "alias: Kitchen Lights\n"
                    "description: Turns on the kitchen lights at 10:00 every day.\n"
                    "triggers:\n"
                    "  - trigger: time\n"
                    '    at: "10:00:00"\n'
                    "conditions: []\n"
                    "actions:\n"
                    "  - action: light.turn_on\n"
                    "    target:\n"
                    "      entity_id: light.kitchen\n"
                    "mode: single\n"
                ),
            },
            {"role": "user", "content": "Change it to 11am instead."},
        ],
        root_prompt="Turn on the kitchen lights at 10am every day",
    )

    entities = [
        {"entity_id": "light.kitchen", "name": "Kitchen", "state": "off", "domain": "light"},
    ]
    fake_client = MagicMock()
    fake_client._request_timeout = 420
    fake_client.complete = AsyncMock(
        return_value={
            "yaml": (
                "alias: Kitchen Lights\n"
                "description: Turns on the kitchen lights at 11:00 every day.\n"
                "triggers:\n"
                "  - trigger: time\n"
                '    at: "11:00:00"\n'
                "conditions: []\n"
                "actions:\n"
                "  - action: light.turn_on\n"
                "    target:\n"
                "      entity_id: light.kitchen\n"
                "mode: single\n"
            ),
            "summary": "Turns on the kitchen lights at 11:00 every day.",
            "needs_clarification": False,
            "clarifying_questions": [],
        }
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
            "Turn on the kitchen lights at 10am every day",
            ["light"],
        )

    assert job["status"] == "completed"
    assert 'at: "11:00:00"' in job["yaml"]
    assert fake_client.complete.await_count == 1
    assert job["conversation_messages"][-1]["role"] == "assistant"
    assert 'at: "11:00:00"' in job["conversation_messages"][-1]["content"]


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


# ---------------------------------------------------------------------------
# Entity extraction & hallucination detection
# ---------------------------------------------------------------------------


def test_extract_entity_ids_from_yaml_basic():
    """Extract entity_id values and notify actions from automation YAML."""
    yaml_text = (
        "alias: Test\n"
        "triggers:\n"
        "  - trigger: state\n"
        "    entity_id: sensor.temperature\n"
        "conditions:\n"
        "  - condition: state\n"
        "    entity_id: binary_sensor.door\n"
        "actions:\n"
        "  - action: light.turn_on\n"
        "    target:\n"
        "      entity_id:\n"
        "        - light.kitchen\n"
        "        - light.bedroom\n"
        "  - action: notify.mobile_app_iphone\n"
        "    data:\n"
        "      message: Hello\n"
        "mode: single\n"
    )
    ids = _extract_entity_ids_from_yaml(yaml_text)
    assert ids == {
        "sensor.temperature",
        "binary_sensor.door",
        "light.kitchen",
        "light.bedroom",
        "notify.mobile_app_iphone",
    }


def test_extract_entity_ids_ignores_service_calls():
    """Service calls like light.turn_on should not be extracted as entity IDs."""
    yaml_text = (
        "alias: Test\n"
        "triggers:\n"
        "  - trigger: state\n"
        "    entity_id: sensor.x\n"
        "actions:\n"
        "  - action: light.turn_on\n"
        "    target:\n"
        "      entity_id: light.kitchen\n"
        "  - action: homeassistant.restart\n"
        "mode: single\n"
    )
    ids = _extract_entity_ids_from_yaml(yaml_text)
    # action: light.turn_on and action: homeassistant.restart are NOT entities
    assert "light.turn_on" not in ids
    assert "homeassistant.restart" not in ids
    assert ids == {"sensor.x", "light.kitchen"}


def test_extract_entity_ids_empty_input():
    """Empty or invalid input returns an empty set."""
    assert _extract_entity_ids_from_yaml("") == set()
    assert _extract_entity_ids_from_yaml("not: {valid: yaml: {{}}") == set()


def test_find_hallucinated_entities():
    """Entities not in the known set are detected as hallucinated."""
    yaml_text = (
        "alias: Test\n"
        "triggers:\n"
        "  - trigger: state\n"
        "    entity_id: sensor.real_sensor\n"
        "conditions: []\n"
        "actions:\n"
        "  - action: light.turn_on\n"
        "    target:\n"
        "      entity_id: light.fake_light\n"
        "  - action: notify.fake_notify\n"
        "    data:\n"
        "      message: test\n"
        "mode: single\n"
    )
    known = {"sensor.real_sensor", "light.real_light", "notify.real_notify"}
    hallucinated = _find_hallucinated_entities(yaml_text, known)
    assert hallucinated == ["light.fake_light", "notify.fake_notify"]


def test_find_hallucinated_entities_all_valid():
    """When all referenced entities are known, returns an empty list."""
    yaml_text = (
        "alias: Test\n"
        "triggers:\n"
        "  - trigger: state\n"
        "    entity_id: sensor.temp\n"
        "conditions: []\n"
        "actions:\n"
        "  - action: light.turn_on\n"
        "    target:\n"
        "      entity_id: light.kitchen\n"
        "mode: single\n"
    )
    known = {"sensor.temp", "light.kitchen"}
    assert _find_hallucinated_entities(yaml_text, known) == []


# ---------------------------------------------------------------------------
# Entity repair integration test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_generation_job_repairs_hallucinated_entities():
    """Unknown entity ids should be surfaced as warnings after the capped repair pass."""
    hass = _make_hass()
    job = _create_generation_job(hass, "Turn on the kitchen lights", ["light"])

    entities = [
        {"entity_id": "light.kitchen", "name": "Kitchen Light", "state": "off", "domain": "light"},
        {"entity_id": "sensor.temperature", "name": "Temperature", "state": "22", "domain": "sensor"},
    ]

    # First response: valid YAML structure but with a hallucinated entity
    hallucinated_response = {
        "yaml": (
            "alias: Kitchen Lights\n"
            "description: \"Turns on the kitchen lights.\"\n"
            "triggers:\n"
            "  - trigger: state\n"
            "    entity_id: sensor.temperature\n"
            '    to: "22"\n'
            "conditions: []\n"
            "actions:\n"
            "  - action: light.turn_on\n"
            "    target:\n"
            "      entity_id: light.nonexistent_light\n"
            "mode: single\n"
        ),
        "summary": "Turns on a nonexistent light.",
        "needs_clarification": False,
        "clarifying_questions": [],
    }

    fake_client = MagicMock()
    fake_client._request_timeout = 420
    fake_client.complete = AsyncMock(return_value=hallucinated_response)

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
            hass, job["job_id"], "Turn on the kitchen lights", ["light"]
        )

    assert job["status"] == "completed"
    assert not job.get("repair_in_progress")
    assert fake_client.complete.await_count == 1
    assert "light.nonexistent_light" in job["yaml"]
    assert any("Unknown entity_ids" in warning for warning in job["warnings"])


# ---- Install-repair endpoint tests ----


@pytest.mark.asyncio
async def test_install_repair_returns_fixed_yaml():
    """install_repair should send the error to the AI and return the corrected YAML."""
    hass = _make_hass()

    fixed_yaml = (
        "alias: Test\ntriggers:\n  - trigger: state\n    entity_id: light.test\n"
        "actions:\n  - action: light.turn_on\n    target:\n      entity_id: light.test\n"
    )
    fake_client = AsyncMock()
    fake_client.complete = AsyncMock(
        return_value={
            "yaml": fixed_yaml,
            "summary": "Fixed automation",
            "needs_clarification": False,
            "clarifying_questions": [],
        }
    )

    body = {
        "yaml": "alias: Test\ntriggers:\n  - trigger: state\nactions:\n  - action: light.test.turn_on\n",
        "error": "does not match format <domain>.<name>",
        "summary": "Turn on light",
    }

    with patch(
        "custom_components.automagic.api.async_get_clientsession",
        return_value=MagicMock(),
    ), patch(
        "custom_components.automagic.api.LLMClient.from_config",
        return_value=fake_client,
    ):
        payload, status = await async_install_repair_request(hass, body)

    assert status == 200
    assert payload["success"] is True
    assert "light.turn_on" in payload["yaml"]


@pytest.mark.asyncio
async def test_install_repair_retries_with_latest_validation_issue():
    """Install repair should send the newest validation failure back to the AI, not just the original error."""
    hass = _make_hass()

    legacy_service_yaml = (
        "alias: Test\n"
        "description: Legacy service draft.\n"
        "triggers:\n"
        "  - trigger: state\n"
        "    entity_id: light.test\n"
        '    to: "on"\n'
        "conditions: []\n"
        "actions:\n"
        "  - service: light.turn_on\n"
        "    target:\n"
        "      entity_id: light.test\n"
        "mode: single\n"
    )
    fixed_yaml = (
        "alias: Test\n"
        "description: Fixed automation.\n"
        "triggers:\n"
        "  - trigger: state\n"
        "    entity_id: light.test\n"
        '    to: "on"\n'
        "conditions: []\n"
        "actions:\n"
        "  - action: light.turn_on\n"
        "    target:\n"
        "      entity_id: light.test\n"
        "mode: single\n"
    )

    fake_client = AsyncMock()

    async def _repair_complete(messages):
        last_content = messages[-1]["content"] if messages else ""
        if "use 'action:' instead of 'service:'" in last_content:
            return {
                "yaml": fixed_yaml,
                "summary": "Fixed automation",
                "needs_clarification": False,
                "clarifying_questions": [],
            }
        return {
            "yaml": legacy_service_yaml,
            "summary": "Legacy service draft",
            "needs_clarification": False,
            "clarifying_questions": [],
        }

    fake_client.complete = AsyncMock(side_effect=_repair_complete)

    body = {
        "yaml": (
            "alias: Test\n"
            "triggers:\n"
            "  - trigger: state\n"
            "    entity_id: light.test\n"
            '    to: "on"\n'
            "conditions: []\n"
            "actions:\n"
            "  - action: light.test.turn_on\n"
            "mode: single\n"
        ),
        "error": "Action 0: 'light.test.turn_on' does not match the required <domain>.<service_name> format",
        "summary": "Turn on light",
    }

    with patch(
        "custom_components.automagic.api.async_get_clientsession",
        return_value=MagicMock(),
    ), patch(
        "custom_components.automagic.api.LLMClient.from_config",
        return_value=fake_client,
    ):
        payload, status = await async_install_repair_request(hass, body)

    assert status == 200
    assert payload["success"] is True
    assert "light.turn_on" in payload["yaml"]
    assert fake_client.complete.await_count == 2
    second_attempt_messages = fake_client.complete.await_args_list[1].args[0]
    assert "Current problems to fix:" in second_attempt_messages[-1]["content"]
    assert "use 'action:' instead of 'service:'" in second_attempt_messages[-1]["content"]


@pytest.mark.asyncio
async def test_install_repair_keeps_retrying_beyond_previous_attempt_cap():
    """Install repair should continue past the old fixed attempt cap until a valid YAML fix arrives."""
    hass = _make_hass()

    legacy_service_yaml = (
        "alias: Test\n"
        "description: Legacy service draft.\n"
        "triggers:\n"
        "  - trigger: state\n"
        "    entity_id: light.test\n"
        '    to: "on"\n'
        "conditions: []\n"
        "actions:\n"
        "  - service: light.turn_on\n"
        "    target:\n"
        "      entity_id: light.test\n"
        "mode: single\n"
    )
    fixed_yaml = (
        "alias: Test\n"
        "description: Fixed automation.\n"
        "triggers:\n"
        "  - trigger: state\n"
        "    entity_id: light.test\n"
        '    to: "on"\n'
        "conditions: []\n"
        "actions:\n"
        "  - action: light.turn_on\n"
        "    target:\n"
        "      entity_id: light.test\n"
        "mode: single\n"
    )

    fake_client = AsyncMock()
    attempt_count = 0

    async def _repair_complete(_messages):
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 7:
            return {
                "yaml": legacy_service_yaml,
                "summary": "Legacy service draft",
                "needs_clarification": False,
                "clarifying_questions": [],
            }
        return {
            "yaml": fixed_yaml,
            "summary": "Fixed automation",
            "needs_clarification": False,
            "clarifying_questions": [],
        }

    fake_client.complete = AsyncMock(side_effect=_repair_complete)

    body = {
        "yaml": (
            "alias: Test\n"
            "triggers:\n"
            "  - trigger: state\n"
            "    entity_id: light.test\n"
            '    to: "on"\n'
            "conditions: []\n"
            "actions:\n"
            "  - action: light.test.turn_on\n"
            "mode: single\n"
        ),
        "error": "Action 0: 'light.test.turn_on' does not match the required <domain>.<service_name> format",
        "summary": "Turn on light",
    }

    with patch(
        "custom_components.automagic.api.async_get_clientsession",
        return_value=MagicMock(),
    ), patch(
        "custom_components.automagic.api.LLMClient.from_config",
        return_value=fake_client,
    ):
        payload, status = await async_install_repair_request(hass, body)

    assert status == 200
    assert payload["success"] is True
    assert "light.turn_on" in payload["yaml"]
    assert _validate_generated_yaml(payload["yaml"]) is None
    assert fake_client.complete.await_count == 7
    late_retry_messages = fake_client.complete.await_args_list[4].args[0]
    assert "Install repair attempt 5." in late_retry_messages[-1]["content"]


@pytest.mark.asyncio
async def test_install_repair_retries_after_model_response_error():
    """Install repair should feed model response errors back into the next repair attempt."""
    hass = _make_hass()

    fixed_yaml = (
        "alias: Test\n"
        "description: Fixed automation.\n"
        "triggers:\n"
        "  - trigger: state\n"
        "    entity_id: light.test\n"
        '    to: "on"\n'
        "conditions: []\n"
        "actions:\n"
        "  - action: light.turn_on\n"
        "    target:\n"
        "      entity_id: light.test\n"
        "mode: single\n"
    )

    fake_client = AsyncMock()
    fake_client.complete = AsyncMock(
        side_effect=[
            LLMResponseError("Failed to parse LLM response as JSON"),
            {
                "yaml": fixed_yaml,
                "summary": "Fixed automation",
                "needs_clarification": False,
                "clarifying_questions": [],
            },
        ]
    )

    body = {
        "yaml": (
            "alias: Test\n"
            "triggers:\n"
            "  - trigger: state\n"
            "    entity_id: light.test\n"
            '    to: "on"\n'
            "conditions: []\n"
            "actions:\n"
            "  - action: light.test.turn_on\n"
            "mode: single\n"
        ),
        "error": "Action 0: 'light.test.turn_on' does not match the required <domain>.<service_name> format",
        "summary": "Turn on light",
    }

    with patch(
        "custom_components.automagic.api.async_get_clientsession",
        return_value=MagicMock(),
    ), patch(
        "custom_components.automagic.api.LLMClient.from_config",
        return_value=fake_client,
    ):
        payload, status = await async_install_repair_request(hass, body)

    assert status == 200
    assert payload["success"] is True
    assert fake_client.complete.await_count == 2
    retry_messages = fake_client.complete.await_args_list[1].args[0]
    assert "still could not be used by AutoMagic" in retry_messages[-1]["content"]
    assert "Failed to parse LLM response as JSON" in retry_messages[-1]["content"]


@pytest.mark.asyncio
async def test_install_repair_missing_fields():
    """install_repair should return 400 when yaml or error is missing."""
    hass = _make_hass()

    payload, status = await async_install_repair_request(hass, {"yaml": "test"})
    assert status == 400
    assert "Missing" in payload["error"]

    payload, status = await async_install_repair_request(hass, {"error": "bad"})
    assert status == 400
    assert "Missing" in payload["error"]


@pytest.mark.asyncio
async def test_install_repair_returns_502_on_llm_error():
    """install_repair should return 502 when the LLM connection fails."""
    hass = _make_hass()

    fake_client = AsyncMock()
    fake_client.complete = AsyncMock(side_effect=LLMConnectionError("timeout"))

    body = {
        "yaml": "alias: Test\ntriggers:\n  - trigger: state\nactions:\n  - action: bad\n",
        "error": "some error",
    }

    with patch(
        "custom_components.automagic.api.async_get_clientsession",
        return_value=MagicMock(),
    ), patch(
        "custom_components.automagic.api.LLMClient.from_config",
        return_value=fake_client,
    ):
        payload, status = await async_install_repair_request(hass, body)

    assert status == 502
    assert "AI repair failed" in payload["error"]
