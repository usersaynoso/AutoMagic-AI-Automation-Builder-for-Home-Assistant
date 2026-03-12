"""Tests for async generation job handling in the API layer."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.automagic.api import (
    AutoMagicGenerateStatusView,
    _create_generation_job,
    _get_config_data,
    _run_generation_job,
)
from custom_components.automagic.const import (
    CONF_ENDPOINT_URL,
    CONF_MODEL,
    CONF_REQUEST_TIMEOUT,
    DOMAIN,
)
from custom_components.automagic.llm_client import LLMConnectionError


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
        return_value={"yaml": "alias: Kitchen Lights", "summary": "Turns on the lights."}
    )

    with patch(
        "custom_components.automagic.api.get_entity_summary_string",
        AsyncMock(return_value="light.kitchen (Kitchen) [off]\nsensor.temp (Temperature) [20]"),
    ), patch(
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
    assert job["yaml"] == "alias: Kitchen Lights"
    assert job["summary"] == "Turns on the lights."
    assert job["entities_used"] == ["light.kitchen"]


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
        "custom_components.automagic.api.get_entity_summary_string",
        AsyncMock(return_value="light.kitchen (Kitchen) [off]"),
    ), patch(
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
        result = await view.get(request)

    assert result["status_code"] == 202
    assert result["status"] == "running"
    assert result["elapsed_seconds"] >= 75
    assert "still running" in result["backend_status"]["message"]
