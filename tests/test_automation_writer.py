"""Tests for automation_writer module."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.automagic.automation_writer import (
    AutomationValidationError,
    install_automation,
    validate_automation,
)


# ---- Validation tests ----

class TestValidateAutomation:
    """Tests for the validate_automation function."""

    def test_valid_new_syntax(self):
        """Valid 2024.10+ automation should pass."""
        parsed = {
            "alias": "Test",
            "triggers": [{"trigger": "state", "entity_id": "light.test"}],
            "actions": [{"action": "light.turn_on", "target": {"entity_id": "light.test"}}],
        }
        validate_automation(parsed)  # Should not raise

    def test_missing_alias(self):
        parsed = {
            "triggers": [{"trigger": "state"}],
            "actions": [{"action": "light.turn_on"}],
        }
        with pytest.raises(AutomationValidationError, match="alias"):
            validate_automation(parsed)

    def test_missing_triggers(self):
        parsed = {
            "alias": "Test",
            "actions": [{"action": "light.turn_on"}],
        }
        with pytest.raises(AutomationValidationError, match="triggers"):
            validate_automation(parsed)

    def test_singular_trigger_at_top_level_rejected(self):
        """Top-level singular 'trigger:' (legacy) should be rejected."""
        parsed = {
            "alias": "Test",
            "trigger": [{"platform": "state"}],
            "actions": [{"action": "light.turn_on"}],
        }
        with pytest.raises(AutomationValidationError, match="triggers.*plural"):
            validate_automation(parsed)

    def test_missing_actions(self):
        parsed = {
            "alias": "Test",
            "triggers": [{"trigger": "state"}],
        }
        with pytest.raises(AutomationValidationError, match="actions"):
            validate_automation(parsed)

    def test_singular_action_at_top_level_rejected(self):
        """Top-level singular 'action:' (legacy) should be rejected."""
        parsed = {
            "alias": "Test",
            "triggers": [{"trigger": "state"}],
            "action": [{"service": "light.turn_on"}],
        }
        with pytest.raises(AutomationValidationError, match="actions.*plural"):
            validate_automation(parsed)

    def test_legacy_platform_in_trigger_rejected(self):
        """Trigger items with 'platform:' but no 'trigger:' should be rejected."""
        parsed = {
            "alias": "Test",
            "triggers": [{"platform": "state", "entity_id": "light.test"}],
            "actions": [{"action": "light.turn_on"}],
        }
        with pytest.raises(AutomationValidationError, match="platform.*legacy"):
            validate_automation(parsed)

    def test_legacy_service_in_action_rejected(self):
        """Action items with 'service:' but no 'action:' should be rejected."""
        parsed = {
            "alias": "Test",
            "triggers": [{"trigger": "state"}],
            "actions": [{"service": "light.turn_on", "target": {}}],
        }
        with pytest.raises(AutomationValidationError, match="service.*legacy"):
            validate_automation(parsed)

    def test_empty_triggers_list_rejected(self):
        parsed = {
            "alias": "Test",
            "triggers": [],
            "actions": [{"action": "light.turn_on"}],
        }
        with pytest.raises(AutomationValidationError, match="non-empty"):
            validate_automation(parsed)

    def test_empty_actions_list_rejected(self):
        parsed = {
            "alias": "Test",
            "triggers": [{"trigger": "state"}],
            "actions": [],
        }
        with pytest.raises(AutomationValidationError, match="non-empty"):
            validate_automation(parsed)

    def test_non_dict_rejected(self):
        with pytest.raises(AutomationValidationError, match="mapping"):
            validate_automation("not a dict")

    def test_with_conditions_valid(self):
        """Conditions are optional - should pass when present."""
        parsed = {
            "alias": "Test",
            "triggers": [{"trigger": "state", "entity_id": "binary_sensor.door"}],
            "conditions": [{"condition": "time", "after": "22:00:00"}],
            "actions": [{"action": "light.turn_on", "target": {"entity_id": "light.hallway"}}],
        }
        validate_automation(parsed)  # Should not raise

    def test_action_format_three_segments_rejected(self):
        """Action with embedded entity_id like 'light.kitchen.turn_on' should be rejected."""
        parsed = {
            "alias": "Test",
            "triggers": [{"trigger": "state", "entity_id": "binary_sensor.door"}],
            "actions": [{"action": "light.kitchen.turn_on"}],
        }
        with pytest.raises(AutomationValidationError, match="<domain>.<service_name> format"):
            validate_automation(parsed)

    def test_action_format_valid_domain_service(self):
        """Actions like 'light.turn_on' must pass the format check."""
        parsed = {
            "alias": "Test",
            "triggers": [{"trigger": "state", "entity_id": "binary_sensor.door"}],
            "actions": [{"action": "light.turn_on", "target": {"entity_id": "light.hallway"}}],
        }
        validate_automation(parsed)  # Should not raise

    def test_action_format_no_dots_rejected(self):
        """An action value with no dot, like 'turn_on', should be rejected."""
        parsed = {
            "alias": "Test",
            "triggers": [{"trigger": "state", "entity_id": "binary_sensor.door"}],
            "actions": [{"action": "turn_on"}],
        }
        with pytest.raises(AutomationValidationError, match="<domain>.<service_name> format"):
            validate_automation(parsed)


# ---- Install tests ----

def _make_hass(config_path: str = "/config", automations_dir_exists: bool = True):
    """Create a mock hass object for install tests."""
    hass = MagicMock()
    hass.config.path = lambda *parts: os.path.join(config_path, *parts)
    hass.services.async_call = AsyncMock()
    hass.async_add_executor_job = AsyncMock()
    return hass


@pytest.mark.asyncio
async def test_install_valid_automation():
    """Test that valid YAML is written and automation.reload is called."""
    hass = _make_hass()
    yaml_string = """\
alias: Test Automation
triggers:
  - trigger: state
    entity_id: binary_sensor.door
    to: "on"
actions:
  - action: light.turn_on
    target:
      entity_id: light.hallway
"""
    with patch("os.path.isdir", return_value=True):
        result = await install_automation(hass, yaml_string)

    assert result["success"] is True
    assert result["alias"] == "Test Automation"
    assert result["filename"] == "automations.yaml"
    hass.async_add_executor_job.assert_called_once()
    call_args = hass.async_add_executor_job.call_args
    assert call_args[0][1] == "/config/automations.yaml"
    assert call_args[0][2]["alias"] == "Test Automation"
    assert "id" in call_args[0][2]
    hass.services.async_call.assert_called_once_with(
        "automation", "reload", blocking=True
    )


@pytest.mark.asyncio
async def test_install_invalid_yaml():
    """Test that invalid YAML returns error."""
    hass = _make_hass()
    result = await install_automation(hass, "not: valid: yaml: [[[")
    assert result["success"] is False
    assert "Invalid YAML" in result["error"]


@pytest.mark.asyncio
async def test_install_salvages_wrapped_yaml_before_validation():
    """Install should accept wrapped yaml strings and extract the automation body."""
    hass = _make_hass()
    yaml_string = """\
yaml
yaml:
alias: Test Automation
triggers:
  - trigger: state
    entity_id: binary_sensor.door
    to: "on"
actions:
  - action: light.turn_on
    target:
      entity_id: light.hallway
"""
    result = await install_automation(hass, yaml_string)

    assert result["success"] is True
    assert result["alias"] == "Test Automation"
    hass.async_add_executor_job.assert_called_once()


@pytest.mark.asyncio
async def test_install_salvages_malformed_json_wrapped_yaml_before_validation():
    """Install should accept broken JSON wrappers that embed raw multiline yaml."""
    hass = _make_hass()
    yaml_string = """\
{"yaml":"
alias: Test Automation
triggers:
  - trigger: state
    entity_id: binary_sensor.door
    to: "on"
actions:
  - action: light.turn_on
    target:
      entity_id: light.hallway
","summary":"Ready for repair","needs_clarification":false}
"""
    result = await install_automation(hass, yaml_string)

    assert result["success"] is True
    assert result["alias"] == "Test Automation"
    hass.async_add_executor_job.assert_called_once()


@pytest.mark.asyncio
async def test_install_quotes_plain_scalar_values_with_colons_before_validation():
    """Install should recover YAML when plain scalar lines contain extra colons."""
    hass = _make_hass()
    yaml_string = """\
alias: Robot vacuum cleaning: weekday morning
description: Every weekday morning: check if the robot vacuum cleaned recently.
triggers:
  - trigger: time
    at: 08:00:00
actions:
  - action: notify.mobile_app_iphone_13
    data:
      message: Warning: Robot vacuum might be stuck
mode: single
"""
    result = await install_automation(hass, yaml_string)

    assert result["success"] is True
    assert result["alias"] == "Robot vacuum cleaning: weekday morning"
    hass.async_add_executor_job.assert_called_once()
    call_args = hass.async_add_executor_job.call_args
    assert call_args[0][2]["description"] == (
        "Every weekday morning: check if the robot vacuum cleaned recently."
    )


@pytest.mark.asyncio
async def test_install_legacy_syntax_rejected():
    """Test that legacy syntax is caught during install."""
    hass = _make_hass()
    yaml_string = """\
alias: Legacy
trigger:
  - platform: state
    entity_id: light.test
actions:
  - action: light.turn_on
"""
    result = await install_automation(hass, yaml_string)
    assert result["success"] is False
    assert "triggers" in result["error"].lower() or "plural" in result["error"].lower()


@pytest.mark.asyncio
async def test_install_fallback_to_config_root():
    """Test writing to automations.yaml in config root."""
    hass = _make_hass()
    yaml_string = """\
alias: Fallback Test
triggers:
  - trigger: state
    entity_id: binary_sensor.door
actions:
  - action: light.turn_on
    target:
      entity_id: light.hallway
"""
    result = await install_automation(hass, yaml_string)

    assert result["success"] is True
    call_args = hass.async_add_executor_job.call_args
    filepath_arg = call_args[0][1]
    assert filepath_arg == "/config/automations.yaml"
    assert call_args[0][2]["alias"] == "Fallback Test"
    assert "id" in call_args[0][2]
