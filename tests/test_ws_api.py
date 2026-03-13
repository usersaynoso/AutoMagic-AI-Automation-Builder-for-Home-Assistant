"""Tests for AutoMagic websocket API registration and handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.automagic.ws_api import (
    async_register_websocket_commands,
    websocket_generate,
    websocket_generate_status,
    websocket_services,
)


def test_register_websocket_commands_registers_all_handlers():
    """AutoMagic should register its websocket command handlers."""
    hass = MagicMock()

    with patch(
        "custom_components.automagic.ws_api.websocket_api.async_register_command"
    ) as register_command:
        async_register_websocket_commands(hass)

    assert register_command.call_count == 6


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
