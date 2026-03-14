"""Tests for async generation job handling in the API layer."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.automagic.api import (
    AutoMagicGenerateView,
    AutoMagicGenerateStatusView,
    _create_generation_job,
    _get_config_data,
    _run_generation_job,
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
from custom_components.automagic.llm_client import LLMConnectionError
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
                    "description: Turn on lights: kitchen alert\n"
                    "triggers:\n"
                    "  - trigger: state\n"
                    "    entity_id: light.kitchen\n"
                    "actions:\n"
                    "  - action: light.turn_on\n"
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
                    "description: Turn on lights: phase alert\n"
                    "triggers:\n"
                    "  - trigger: template\n"
                    "actions:\n"
                    "  - action: notify.mobile_app_iphone_13\n"
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
