"""REST API views for AutoMagic."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .automation_writer import install_automation
from .const import (
    API_PATH_ENTITIES,
    API_PATH_GENERATE,
    API_PATH_HISTORY,
    API_PATH_INSTALL,
    DOMAIN,
)
from .entity_collector import get_entity_context, get_entity_summary_string
from .llm_client import LLMClient, LLMConnectionError, LLMResponseError
from .prompt_builder import build_prompt

_LOGGER = logging.getLogger(__name__)
_HISTORY_FILE = "automagic_history.json"


def _history_path(hass: HomeAssistant) -> str:
    """Return the path to the history JSON file."""
    return hass.config.path(_HISTORY_FILE)


def _load_history(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Load automation history from disk."""
    path = _history_path(hass)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_history(hass: HomeAssistant, history: list[dict[str, Any]]) -> None:
    """Persist automation history to disk."""
    path = _history_path(hass)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def _append_history(
    hass: HomeAssistant,
    prompt: str,
    alias: str,
    summary: str,
    yaml_str: str,
    filename: str,
    success: bool,
) -> None:
    """Add an entry to the automation history."""
    from datetime import datetime, timezone

    history = _load_history(hass)
    history.insert(
        0,
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prompt": prompt,
            "alias": alias,
            "summary": summary,
            "yaml": yaml_str,
            "filename": filename,
            "success": success,
        },
    )
    # Keep last 100 entries
    history = history[:100]
    _save_history(hass, history)


class AutoMagicGenerateView(HomeAssistantView):
    """Handle POST /api/automagic/generate."""

    url = API_PATH_GENERATE
    name = "api:automagic:generate"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Generate an automation from a natural language prompt."""
        hass: HomeAssistant = request.app["hass"]

        try:
            body = await request.json()
        except ValueError:
            return self.json({"error": "Invalid JSON body"}, status_code=400)

        prompt_text = body.get("prompt", "").strip()
        if not prompt_text:
            return self.json({"error": "Missing 'prompt' field"}, status_code=400)

        entity_filter = body.get("entity_filter")

        # Get config
        config_data = _get_config_data(hass)
        if config_data is None:
            return self.json(
                {"error": "AutoMagic is not configured"}, status_code=500
            )

        # Collect all entities (no artificial cap)
        try:
            entity_summary = await get_entity_summary_string(hass)
            entities_list = await get_entity_context(hass)
        except Exception as err:
            _LOGGER.error("Failed to collect entities: %s", err)
            return self.json(
                {"error": f"Failed to collect entities: {err}"}, status_code=500
            )

        # Filter entities by domain if requested
        if entity_filter and isinstance(entity_filter, list):
            filtered = [e for e in entities_list if e["domain"] in entity_filter]
            lines = [
                f"{e['entity_id']} ({e['name']}) [{e['state']}]" for e in filtered
            ]
            entity_summary = "\n".join(lines)

        # Build prompt and call LLM
        messages = build_prompt(prompt_text, entity_summary)

        session = async_get_clientsession(hass)
        client = LLMClient.from_config(config_data, session=session)

        try:
            result = await client.complete(messages)
        except LLMConnectionError as err:
            _LOGGER.error("LLM connection error: %s", err)
            return self.json({"error": str(err)}, status_code=502)
        except LLMResponseError as err:
            _LOGGER.error("LLM response error: %s", err)
            return self.json({"error": str(err)}, status_code=502)

        return self.json(
            {
                "yaml": result.get("yaml"),
                "summary": result.get("summary"),
                "entities_used": [
                    e["entity_id"] for e in entities_list
                ],
                "error": None,
            }
        )


class AutoMagicInstallView(HomeAssistantView):
    """Handle POST /api/automagic/install."""

    url = API_PATH_INSTALL
    name = "api:automagic:install"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Install a generated automation into Home Assistant."""
        hass: HomeAssistant = request.app["hass"]

        try:
            body = await request.json()
        except ValueError:
            return self.json({"error": "Invalid JSON body"}, status_code=400)

        yaml_string = body.get("yaml", "").strip()
        if not yaml_string:
            return self.json(
                {"error": "Missing 'yaml' field"}, status_code=400
            )

        prompt = body.get("prompt", "")
        summary = body.get("summary", "")

        result = await install_automation(hass, yaml_string)
        status = 200 if result.get("success") else 400

        # Record in history
        await hass.async_add_executor_job(
            _append_history,
            hass,
            prompt,
            result.get("alias", ""),
            summary,
            yaml_string,
            result.get("filename", ""),
            result.get("success", False),
        )

        return self.json(result, status_code=status)


class AutoMagicEntitiesView(HomeAssistantView):
    """Handle GET /api/automagic/entities."""

    url = API_PATH_ENTITIES
    name = "api:automagic:entities"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Return the entity summary list as JSON."""
        hass: HomeAssistant = request.app["hass"]

        try:
            entities = await get_entity_context(hass)
        except Exception as err:
            _LOGGER.error("Failed to collect entities: %s", err)
            return self.json(
                {"error": f"Failed to collect entities: {err}"}, status_code=500
            )

        return self.json({"entities": entities})


class AutoMagicHistoryView(HomeAssistantView):
    """Handle GET /api/automagic/history."""

    url = API_PATH_HISTORY
    name = "api:automagic:history"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Return the automation creation history."""
        hass: HomeAssistant = request.app["hass"]
        history = await hass.async_add_executor_job(_load_history, hass)
        return self.json({"history": history})


def _get_config_data(hass: HomeAssistant) -> dict[str, Any] | None:
    """Get the config data from the first AutoMagic config entry."""
    domain_data = hass.data.get(DOMAIN, {})
    for entry_data in domain_data.values():
        if isinstance(entry_data, dict):
            return entry_data
    return None
