"""Tests for programmatic YAML autofix helpers."""

from __future__ import annotations

import yaml

from custom_components.automagic.yaml_autofix import autofix_yaml


def test_autofix_normalizes_legacy_keys_and_injects_light_and_guard_data():
    """Autofix should handle legacy syntax, missing light data, and top-level guards."""
    prompt = (
        "When the front door opens, turn the bar lamp warm white at 20% brightness. "
        "Don't start it if the router LED switch is already off."
    )
    entities = [
        {
            "entity_id": "binary_sensor.front_door",
            "name": "Front Door",
            "domain": "binary_sensor",
        },
        {
            "entity_id": "light.bar_lamp",
            "name": "Bar Lamp",
            "domain": "light",
        },
        {
            "entity_id": "switch.router_led",
            "name": "Router LED Switch",
            "domain": "switch",
        },
    ]
    yaml_text = """alias: Warm Lamp
description: Example
trigger:
  - platform: state
    entity_id: binary_sensor.front_door
    to: "on"
action:
  - service: light.turn_on
    target:
      entity_id: light.bar_lamp
mode: single
"""

    fixed_yaml, fixes = autofix_yaml(yaml_text, prompt, entities)
    parsed = yaml.safe_load(fixed_yaml)

    assert parsed["triggers"][0]["trigger"] == "state"
    assert parsed["actions"][0]["action"] == "light.turn_on"
    assert parsed["actions"][0]["data"]["color_temp"] == 370
    assert parsed["actions"][0]["data"]["brightness_pct"] == 20
    assert {
        "condition": "state",
        "entity_id": "switch.router_led",
        "state": "on",
    } in parsed["conditions"]
    assert any("Renamed top-level trigger:" in fix for fix in fixes)
    assert any("Injected missing light data" in fix for fix in fixes)


def test_autofix_adds_wait_timeout_and_wraps_timeout_notification():
    """Timeout prompts should become wait_for_trigger plus a choose branch."""
    prompt = "If Janet is still cleaning after 90 minutes, notify my iPhone."
    entities = [
        {
            "entity_id": "vacuum.janet",
            "name": "Janet",
            "domain": "vacuum",
        },
        {
            "entity_id": "notify.mobile_app_iphone",
            "name": "Notify Iphone",
            "domain": "notify",
        },
    ]
    yaml_text = """alias: Janet Timeout
description: Example
triggers:
  - trigger: state
    entity_id: vacuum.janet
    to: "cleaning"
conditions: []
actions:
  - wait_for_trigger:
      - platform: state
        entity_id: vacuum.janet
        to: "docked"
  - action: notify.mobile_app_iphone
    message: "Janet is still cleaning"
mode: single
"""

    fixed_yaml, fixes = autofix_yaml(yaml_text, prompt, entities)
    parsed = yaml.safe_load(fixed_yaml)

    assert parsed["actions"][0]["wait_for_trigger"][0]["trigger"] == "state"
    assert parsed["actions"][0]["timeout"] == "01:30:00"
    assert parsed["actions"][0]["continue_on_timeout"] is True
    assert "choose" in parsed["actions"][1]
    choose_action = parsed["actions"][1]["choose"][0]["sequence"][0]
    assert choose_action["action"] == "notify.mobile_app_iphone"
    assert choose_action["data"]["message"] == "Janet is still cleaning"
    assert any("Wrapped the timeout notification" in fix for fix in fixes)


def test_autofix_converts_action_delay_steps_into_real_delay_keys():
    """Legacy action: delay drafts should become valid script delay steps."""
    fixed_yaml, fixes = autofix_yaml(
        """alias: Kitchen Lights
description: Example
triggers:
  - trigger: state
    entity_id: light.kitchen
    to: "on"
conditions: []
actions:
  - action: delay
    data:
      duration: "00:05:00"
  - action: light.turn_on
    target:
      entity_id: light.kitchen
mode: single
""",
        "Turn on the kitchen lights after five minutes.",
        [{"entity_id": "light.kitchen", "name": "Kitchen", "domain": "light"}],
    )
    parsed = yaml.safe_load(fixed_yaml)

    assert parsed["actions"][0] == {"delay": "00:05:00"}
    assert any("Converted action: delay" in fix for fix in fixes)
