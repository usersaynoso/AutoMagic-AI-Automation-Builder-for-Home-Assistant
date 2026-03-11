"""Validate and write automations to Home Assistant."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any

import yaml

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Legacy keys that must NOT appear in new-syntax automations
_LEGACY_TRIGGER_KEY = "platform"
_LEGACY_ACTION_KEY = "service"


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
        if _LEGACY_ACTION_KEY in act and "action" not in act:
            raise AutomationValidationError(
                f"Action {i}: use 'action:' instead of 'service:' (legacy syntax rejected)"
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
    short_id = uuid.uuid4().hex[:8]
    filename = f"automagic_{short_id}.yaml"

    # Determine where to write
    automations_dir = hass.config.path("automations")
    if os.path.isdir(automations_dir):
        filepath = os.path.join(automations_dir, filename)
    else:
        # Fallback: write to config root alongside automations.yaml
        filepath = hass.config.path(filename)

    # Write the file
    try:
        # Wrap in a list so HA can merge it with other automation files
        automation_list = [parsed]
        yaml_output = yaml.dump(
            automation_list,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
        await hass.async_add_executor_job(_write_file, filepath, yaml_output)
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
    return {"success": True, "alias": alias, "filename": filename}


def _write_file(filepath: str, content: str) -> None:
    """Write content to a file (runs in executor)."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
