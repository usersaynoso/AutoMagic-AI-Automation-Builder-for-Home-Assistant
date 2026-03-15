"""Validate and write automations to Home Assistant."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from typing import Any

import yaml

from homeassistant.core import HomeAssistant

from .llm_client import _normalize_automation_yaml_text

_LOGGER = logging.getLogger(__name__)

# Legacy keys that must NOT appear in new-syntax automations
_LEGACY_TRIGGER_KEY = "platform"
_LEGACY_ACTION_KEY = "service"
_ACTION_FORMAT_RE = re.compile(r"^[a-z_]+\.[a-z_0-9]+$")
_INVALID_SCENE_SERVICES = {
    "scene.turn_all_off",
    "scene.turn_all_on",
}
_TOP_LEVEL_WEEKDAY_ERROR = (
    "'weekday:' is not a valid top-level automation key. Weekday restrictions "
    "must go inside a 'condition: time' block under conditions: or inside a "
    "trigger's 'at:' schedule."
)


def _nested_trigger_mapping_error(index: int) -> str:
    """Return the validation error for nested trigger mappings."""
    return (
        f"Trigger {index}: 'trigger:' must be a plain string like 'trigger: time', "
        "not a nested mapping. Found 'trigger:' used as a block instead of a scalar."
    )


def _bare_action_condition_error(index: int) -> str:
    """Return the validation error for invalid action-list conditions."""
    return (
        f"Action {index}: bare 'condition:' inside actions: is not valid flow control. "
        "Use a 'choose:' block with a 'conditions:' list and 'sequence:' to branch, "
        "or move the condition to the top-level conditions: block."
    )


class AutomationValidationError(Exception):
    """Raised when automation YAML fails validation."""


def validate_automation(parsed: dict[str, Any]) -> None:
    """Validate that parsed automation dict uses 2024.10+ syntax.

    Raises AutomationValidationError on any legacy syntax or missing keys.
    """
    if not isinstance(parsed, dict):
        raise AutomationValidationError("Automation must be a YAML mapping")

    # Must have alias
    if "alias" not in parsed:
        raise AutomationValidationError("Automation must include 'alias'")

    if "weekday" in parsed:
        raise AutomationValidationError(_TOP_LEVEL_WEEKDAY_ERROR)

    # Must use plural 'triggers:' at top level
    if "triggers" not in parsed:
        if "trigger" in parsed:
            raise AutomationValidationError(
                "Use 'triggers:' (plural) at the top level, not 'trigger:'. "
                "This is the HA 2024.10+ syntax."
            )
        raise AutomationValidationError("Automation must include 'triggers:'")

    # Must use plural 'actions:' at top level
    if "actions" not in parsed:
        if "action" in parsed:
            raise AutomationValidationError(
                "Use 'actions:' (plural) at the top level, not 'action:'. "
                "This is the HA 2024.10+ syntax."
            )
        raise AutomationValidationError("Automation must include 'actions:'")

    # Validate triggers list
    triggers = parsed["triggers"]
    if not isinstance(triggers, list) or len(triggers) == 0:
        raise AutomationValidationError("'triggers:' must be a non-empty list")

    for i, trig in enumerate(triggers):
        if not isinstance(trig, dict):
            continue
        if isinstance(trig.get("trigger"), dict):
            raise AutomationValidationError(_nested_trigger_mapping_error(i))
        if _LEGACY_TRIGGER_KEY in trig and "trigger" not in trig:
            raise AutomationValidationError(
                f"Trigger {i}: use 'trigger:' instead of 'platform:' (legacy syntax rejected)"
            )

    # Validate actions list
    actions = parsed["actions"]
    if not isinstance(actions, list) or len(actions) == 0:
        raise AutomationValidationError("'actions:' must be a non-empty list")

    for i, act in enumerate(actions):
        if not isinstance(act, dict):
            continue
        if "condition" in act:
            raise AutomationValidationError(_bare_action_condition_error(i))
        # Only inspect top-level keys on action items. Nested wait_for_trigger
        # sub-triggers legitimately use platform: in Home Assistant.
        if _LEGACY_ACTION_KEY in act and "action" not in act:
            raise AutomationValidationError(
                f"Action {i}: use 'action:' instead of 'service:' (legacy syntax rejected)"
            )
        action_value = act.get("action")
        if isinstance(action_value, str) and action_value and not _ACTION_FORMAT_RE.match(action_value):
            raise AutomationValidationError(
                f"Action {i}: '{action_value}' does not match the required "
                f"<domain>.<service_name> format (e.g. 'light.turn_on', not "
                f"'light.kitchen.turn_on'). Use action: <domain>.<service> with "
                f"a separate target: entity_id: field."
            )
        if isinstance(action_value, str) and action_value in _INVALID_SCENE_SERVICES:
            raise AutomationValidationError(
                f"Action {i}: '{action_value}' is not a valid Home Assistant service. "
                "Scenes are activated with 'action: scene.turn_on' and a 'target: entity_id:' field. "
                "There is no turn_all_off or turn_all_on scene service."
            )


async def install_automation(
    hass: HomeAssistant, yaml_string: str
) -> dict[str, Any]:
    """Validate and install an automation into Home Assistant.

    Args:
        hass: The Home Assistant instance.
        yaml_string: The raw YAML string of the automation.

    Returns:
        A dict with success status, alias, filename, or error message.
    """
    yaml_string = _normalize_automation_yaml_text(yaml_string)

    # Parse YAML
    try:
        parsed = yaml.safe_load(yaml_string)
    except yaml.YAMLError as err:
        return {"success": False, "error": f"Invalid YAML: {err}"}

    # Validate structure and syntax
    try:
        validate_automation(parsed)
    except AutomationValidationError as err:
        return {"success": False, "error": str(err)}

    alias = parsed["alias"]
    if "id" not in parsed:
        parsed = {"id": uuid.uuid4().hex, **parsed}

    filepath = hass.config.path("automations.yaml")

    # Write the file
    try:
        await hass.async_add_executor_job(_append_automation, filepath, parsed)
    except OSError as err:
        _LOGGER.error("Failed to write automation file %s: %s", filepath, err)
        return {"success": False, "error": f"Failed to write file: {err}"}

    # Reload automations
    try:
        await hass.services.async_call("automation", "reload", blocking=True)
        await asyncio.sleep(1)
    except Exception as err:
        _LOGGER.warning("Automation reload may have failed: %s", err)
        # Don't fail the install - file was written successfully

    _LOGGER.info("Installed automation '%s' to %s", alias, filepath)
    return {"success": True, "alias": alias, "filename": "automations.yaml"}


def _write_file(filepath: str, content: str) -> None:
    """Write content to a file (runs in executor)."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)


def _append_automation(filepath: str, automation: dict[str, Any]) -> None:
    """Append a single automation entry to automations.yaml without rewriting existing data."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    snippet = yaml.dump(
        [automation],
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )

    if os.path.exists(filepath):
        with open(filepath, encoding="utf-8") as f:
            existing = f.read()
    else:
        existing = ""

    with open(filepath, "a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        if existing.strip():
            f.write("\n")
        f.write(snippet)
