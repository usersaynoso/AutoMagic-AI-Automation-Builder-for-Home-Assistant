"""Websocket API commands for AutoMagic."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .api import (
    async_delete_history_entry_request,
    async_get_entities_payload,
    async_get_generation_status_payload,
    async_get_history_payload,
    async_get_services_payload,
    async_install_automation_request,
    async_install_repair_request,
    async_start_generation_request,
)


@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required("type"): "automagic/generate",
        vol.Required("prompt"): str,
        vol.Optional("entity_filter"): [str],
        vol.Optional("continue_job_id"): str,
        vol.Optional("service_id"): str,
    }
)
async def websocket_generate(
    hass: HomeAssistant, connection: Any, msg: dict[str, Any]
) -> None:
    """Start a generation job over the authenticated HA websocket."""
    payload, _status = await async_start_generation_request(hass, msg)
    connection.send_result(msg["id"], payload)


@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required("type"): "automagic/generate_status",
        vol.Required("job_id"): str,
    }
)
async def websocket_generate_status(
    hass: HomeAssistant, connection: Any, msg: dict[str, Any]
) -> None:
    """Return the current generation job status over websocket."""
    payload, _status = await async_get_generation_status_payload(hass, msg["job_id"])
    connection.send_result(msg["id"], payload)


@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required("type"): "automagic/install",
        vol.Required("yaml"): str,
        vol.Optional("prompt"): str,
        vol.Optional("summary"): str,
    }
)
async def websocket_install(
    hass: HomeAssistant, connection: Any, msg: dict[str, Any]
) -> None:
    """Install a generated automation over websocket."""
    payload, _status = await async_install_automation_request(hass, msg)
    connection.send_result(msg["id"], payload)


@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required("type"): "automagic/entities",
    }
)
async def websocket_entities(
    hass: HomeAssistant, connection: Any, msg: dict[str, Any]
) -> None:
    """Return entity context data over websocket."""
    payload, _status = await async_get_entities_payload(hass)
    connection.send_result(msg["id"], payload)


@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required("type"): "automagic/history",
    }
)
async def websocket_history(
    hass: HomeAssistant, connection: Any, msg: dict[str, Any]
) -> None:
    """Return generation history over websocket."""
    payload, _status = await async_get_history_payload(hass)
    connection.send_result(msg["id"], payload)


@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required("type"): "automagic/history_delete",
        vol.Required("entry_id"): str,
    }
)
async def websocket_history_delete(
    hass: HomeAssistant, connection: Any, msg: dict[str, Any]
) -> None:
    """Delete a removable history row over websocket."""
    payload, status = await async_delete_history_entry_request(
        hass,
        msg["entry_id"],
    )
    if status >= 400:
        connection.send_error(
            msg["id"],
            "history_delete_failed",
            payload.get("error", "Failed to delete history entry"),
        )
        return
    connection.send_result(msg["id"], payload)


@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required("type"): "automagic/install_repair",
        vol.Required("yaml"): str,
        vol.Required("error"): str,
        vol.Optional("summary"): str,
        vol.Optional("service_id"): str,
    }
)
async def websocket_install_repair(
    hass: HomeAssistant, connection: Any, msg: dict[str, Any]
) -> None:
    """Send an install error back to the AI for repair over websocket."""
    payload, _status = await async_install_repair_request(hass, msg)
    connection.send_result(msg["id"], payload)


@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required("type"): "automagic/services",
    }
)
async def websocket_services(
    hass: HomeAssistant, connection: Any, msg: dict[str, Any]
) -> None:
    """Return configured AI services over websocket."""
    payload, _status = await async_get_services_payload(hass)
    connection.send_result(msg["id"], payload)


def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register AutoMagic websocket commands."""
    websocket_api.async_register_command(hass, websocket_generate)
    websocket_api.async_register_command(hass, websocket_generate_status)
    websocket_api.async_register_command(hass, websocket_install)
    websocket_api.async_register_command(hass, websocket_entities)
    websocket_api.async_register_command(hass, websocket_history)
    websocket_api.async_register_command(hass, websocket_history_delete)
    websocket_api.async_register_command(hass, websocket_install_repair)
    websocket_api.async_register_command(hass, websocket_services)
