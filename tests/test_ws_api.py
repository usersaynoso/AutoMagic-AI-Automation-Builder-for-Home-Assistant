"""Tests for AutoMagic websocket API registration and handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.automagic.ws_api import (
    async_register_websocket_commands,
    websocket_generate,
    websocket_generate_status,
    websocket_history_delete,
    websocket_install_repair,
    websocket_services,
)


def test_register_websocket_commands_registers_all_handlers():
    """AutoMagic should register its websocket command handlers."""
    hass = MagicMock()

    with patch(
        "custom_components.automagic.ws_api.websocket_api.async_register_command"
    ) as register_command:
        async_register_websocket_commands(hass)

    assert register_command.call_count == 8


@pytest.mark.asyncio
async def test_websocket_generate_sends_generation_result():
    """Generate websocket handler should return the shared payload."""
    hass = MagicMock()
    connection = MagicMock()
    msg = {"id": 7, "type": "automagic/generate", "prompt": "Test prompt"}

    with patch(
        "custom_components.automagic.ws_api.async_start_generation_request",
        AsyncMock(return_value=({"job_id": "abc123", "status": "queued"}, 202)),
    ):
        await websocket_generate(hass, connection, msg)

    connection.send_result.assert_called_once_with(
        7, {"job_id": "abc123", "status": "queued"}
    )


@pytest.mark.asyncio
async def test_websocket_status_sends_status_payload():
    """Status websocket handler should return the shared polling payload."""
    hass = MagicMock()
    connection = MagicMock()
    msg = {"id": 9, "type": "automagic/generate_status", "job_id": "job-1"}

    with patch(
        "custom_components.automagic.ws_api.async_get_generation_status_payload",
        AsyncMock(return_value=({"job_id": "job-1", "status": "running"}, 202)),
    ):
        await websocket_generate_status(hass, connection, msg)

    connection.send_result.assert_called_once_with(
        9, {"job_id": "job-1", "status": "running"}
    )


@pytest.mark.asyncio
async def test_websocket_services_sends_service_payload():
    """Services websocket handler should return the configured picker payload."""
    hass = MagicMock()
    connection = MagicMock()
    msg = {"id": 11, "type": "automagic/services"}

    with patch(
        "custom_components.automagic.ws_api.async_get_services_payload",
        AsyncMock(
            return_value=(
                {
                    "services": [{"service_id": "primary"}],
                    "default_service_id": "primary",
                },
                200,
            )
        ),
    ):
        await websocket_services(hass, connection, msg)

    connection.send_result.assert_called_once_with(
        11,
        {
            "services": [{"service_id": "primary"}],
            "default_service_id": "primary",
        },
    )


@pytest.mark.asyncio
async def test_websocket_history_delete_sends_updated_history():
    """History delete websocket handler should return the refreshed history payload."""
    hass = MagicMock()
    connection = MagicMock()
    msg = {"id": 13, "type": "automagic/history_delete", "entry_id": "failed-1"}

    with patch(
        "custom_components.automagic.ws_api.async_delete_history_entry_request",
        AsyncMock(return_value=({"history": [{"entry_id": "installed-1"}]}, 200)),
    ):
        await websocket_history_delete(hass, connection, msg)

    connection.send_result.assert_called_once_with(
        13,
        {"history": [{"entry_id": "installed-1"}]},
    )


@pytest.mark.asyncio
async def test_websocket_history_delete_sends_errors_for_blocked_rows():
    """History delete websocket handler should reject non-removable rows."""
    hass = MagicMock()
    connection = MagicMock()
    msg = {"id": 15, "type": "automagic/history_delete", "entry_id": "installed-1"}

    with patch(
        "custom_components.automagic.ws_api.async_delete_history_entry_request",
        AsyncMock(
            return_value=(
                {"error": "Only failed or deleted history entries can be removed"},
                400,
            )
        ),
    ):
        await websocket_history_delete(hass, connection, msg)

    connection.send_error.assert_called_once_with(
        15,
        "history_delete_failed",
        "Only failed or deleted history entries can be removed",
    )


@pytest.mark.asyncio
async def test_websocket_install_repair_sends_repaired_yaml():
    """Install-repair websocket handler should relay the AI-fixed YAML."""
    hass = MagicMock()
    connection = MagicMock()
    msg = {
        "id": 17,
        "type": "automagic/install_repair",
        "yaml": "alias: Broken\ntriggers:\n  - trigger: state\nactions:\n  - action: light.bad.turn_on\n",
        "error": "does not match format <domain>.<name>",
        "summary": "Turn on light",
    }

    with patch(
        "custom_components.automagic.ws_api.async_install_repair_request",
        AsyncMock(
            return_value=(
                {"success": True, "yaml": "alias: Fixed\ntriggers:\n  - trigger: state\nactions:\n  - action: light.turn_on\n", "summary": "Turn on light"},
                200,
            )
        ),
    ):
        await websocket_install_repair(hass, connection, msg)

    connection.send_result.assert_called_once_with(
        17,
        {
            "success": True,
            "yaml": "alias: Fixed\ntriggers:\n  - trigger: state\nactions:\n  - action: light.turn_on\n",
            "summary": "Turn on light",
        },
    )
