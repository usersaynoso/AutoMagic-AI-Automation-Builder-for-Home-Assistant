"""REST API views for AutoMagic."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .automation_writer import install_automation
from .const import (
    API_PATH_ENTITIES,
    API_PATH_GENERATE,
    API_PATH_INSTALL,
    CONF_CONTEXT_LIMIT,
    DEFAULT_CONTEXT_LIMIT,
    DOMAIN,
)
from .entity_collector import get_entity_context, get_entity_summary_string
from .llm_client import LLMClient, LLMConnectionError, LLMResponseError
from .prompt_builder import build_prompt

_LOGGER = logging.getLogger(__name__)


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

        max_entities = config_data.get(CONF_CONTEXT_LIMIT, DEFAULT_CONTEXT_LIMIT)

        # Collect entities
        try:
            entity_summary = await get_entity_summary_string(hass, max_entities)
            entities_list = await get_entity_context(hass, max_entities)
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

        result = await install_automation(hass, yaml_string)
        status = 200 if result.get("success") else 400
        return self.json(result, status_code=status)


class AutoMagicEntitiesView(HomeAssistantView):
    """Handle GET /api/automagic/entities."""

    url = API_PATH_ENTITIES
    name = "api:automagic:entities"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Return the entity summary list as JSON."""
        hass: HomeAssistant = request.app["hass"]

        config_data = _get_config_data(hass)
        max_entities = (
            config_data.get(CONF_CONTEXT_LIMIT, DEFAULT_CONTEXT_LIMIT)
            if config_data
            else DEFAULT_CONTEXT_LIMIT
        )

        try:
            entities = await get_entity_context(hass, max_entities)
        except Exception as err:
            _LOGGER.error("Failed to collect entities: %s", err)
            return self.json(
                {"error": f"Failed to collect entities: {err}"}, status_code=500
            )

        return self.json({"entities": entities})


def _get_config_data(hass: HomeAssistant) -> dict[str, Any] | None:
    """Get the config data from the first AutoMagic config entry."""
    domain_data = hass.data.get(DOMAIN, {})
    for entry_data in domain_data.values():
        if isinstance(entry_data, dict):
            return entry_data
    return None
