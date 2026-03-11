"""Collect and format Home Assistant entities for LLM context."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import PRIORITY_DOMAINS

_LOGGER = logging.getLogger(__name__)


async def get_entity_context(
    hass: HomeAssistant, max_entities: int = 40
) -> list[dict[str, Any]]:
    """Pull entities from the registry and return a prioritised, truncated list.

    Returns a list of dicts with keys:
        entity_id, name, domain, state, device_class
    """
    registry = er.async_get(hass)
    entities: list[dict[str, Any]] = []

    for entry in registry.entities.values():
        if entry.disabled_by is not None:
            continue

        domain = entry.domain
        state_obj = hass.states.get(entry.entity_id)
        state_value = state_obj.state if state_obj else "unknown"
        friendly_name = (
            entry.name
            or entry.original_name
            or (state_obj.attributes.get("friendly_name") if state_obj else None)
            or entry.entity_id
        )
        device_class = (
            entry.device_class
            or entry.original_device_class
            or (state_obj.attributes.get("device_class") if state_obj else None)
        )

        entities.append(
            {
                "entity_id": entry.entity_id,
                "name": friendly_name,
                "domain": domain,
                "state": state_value,
                "device_class": device_class,
            }
        )

    # Build priority index (lower = higher priority)
    priority_index = {d: i for i, d in enumerate(PRIORITY_DOMAINS)}
    fallback_priority = len(PRIORITY_DOMAINS)

    # Sort: priority domains first, then alphabetically by domain, then by name
    entities.sort(
        key=lambda e: (
            priority_index.get(e["domain"], fallback_priority),
            e["domain"],
            e["name"],
        )
    )

    truncated = entities[:max_entities]
    _LOGGER.debug(
        "Entity collector: %d total, returning %d (limit %d)",
        len(entities),
        len(truncated),
        max_entities,
    )
    return truncated


async def get_entity_summary_string(
    hass: HomeAssistant, max_entities: int = 40
) -> str:
    """Return a compact string of entities for injection into the LLM prompt.

    Format: one entity per line: `light.living_room_lamp (Living Room Lamp) [on]`
    """
    entities = await get_entity_context(hass, max_entities)
    lines: list[str] = []
    for e in entities:
        lines.append(f"{e['entity_id']} ({e['name']}) [{e['state']}]")
    return "\n".join(lines)
