"""Tests for programmatic YAML autofix helpers."""

from __future__ import annotations

import yaml

from custom_components.automagic.yaml_autofix import autofix_yaml
from custom_components.automagic.validation import validate_generated_yaml


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


def test_autofix_injects_entity_map_guards_without_duplication():
    """Entity-map guard roles should become top-level conditions exactly once."""
    prompt = "Don't run if either router LED switch is off."
    entities = [
        {
            "entity_id": "switch.main_router_led",
            "name": "Main Router LED",
            "domain": "switch",
            "state": "off",
        },
        {
            "entity_id": "switch.mesh_router_led",
            "name": "Mesh Router LED",
            "domain": "switch",
            "state": "on",
        },
    ]
    entity_map = {
        "router led switches": {
            "role": "guard",
            "entity_ids": [
                "switch.main_router_led",
                "switch.mesh_router_led",
            ],
            "required_state": "on",
            "blocked_state": "off",
        }
    }
    yaml_text = """alias: Router Guard
description: Example
triggers: []
conditions:
  - condition: state
    entity_id: switch.main_router_led
    state: "on"
actions: []
mode: single
"""

    fixed_yaml, fixes = autofix_yaml(yaml_text, prompt, entities, entity_map)
    parsed = yaml.safe_load(fixed_yaml)

    matching = [
        condition
        for condition in parsed["conditions"]
        if condition.get("condition") == "state"
        and condition.get("state") == "on"
    ]
    assert matching.count(
        {
            "condition": "state",
            "entity_id": "switch.main_router_led",
            "state": "on",
        }
    ) == 1
    assert {
        "condition": "state",
        "entity_id": "switch.mesh_router_led",
        "state": "on",
    } in parsed["conditions"]
    assert fixes.count(
        "Injected missing guard condition for switch.mesh_router_led from entity map"
    ) == 1


def test_autofix_fixes_notify_targets_and_removes_target_blocks_recursively():
    """Resolved notify targets should replace incorrect notify services everywhere."""
    prompt = "Notify my iPhone if the washing machine is still running."
    entities = [
        {
            "entity_id": "notify.mobile_app_iphone_13",
            "name": "Notify iPhone 13",
            "domain": "notify",
        }
    ]
    entity_map = {
        "my iphone": {
            "role": "notify_target",
            "entity_ids": ["notify.mobile_app_iphone_13"],
        }
    }
    yaml_text = """alias: Notify
description: Example
triggers: []
conditions: []
actions:
  - choose:
      - conditions: []
        sequence:
          - action: notify.send_message
            target:
              entity_id:
                - notify.send_message
            data:
              message: "Nested notice"
    default:
      - action: notify.notify
        data:
          message: "Fallback"
  - if:
      - condition: template
        value_template: "{{ true }}"
    then:
      - repeat:
          sequence:
            - action: notify.bad_target
              target:
                entity_id: notify.bad_target
              data:
                message: "Repeat"
    else:
      - action: light.turn_on
        target:
          entity_id: light.kitchen
mode: single
"""

    fixed_yaml, fixes = autofix_yaml(yaml_text, prompt, entities, entity_map)
    parsed = yaml.safe_load(fixed_yaml)

    nested_notify = parsed["actions"][0]["choose"][0]["sequence"][0]
    default_notify = parsed["actions"][0]["default"][0]
    repeated_notify = parsed["actions"][1]["then"][0]["repeat"]["sequence"][0]

    assert nested_notify["action"] == "notify.mobile_app_iphone_13"
    assert default_notify["action"] == "notify.mobile_app_iphone_13"
    assert repeated_notify["action"] == "notify.mobile_app_iphone_13"
    assert "target" not in nested_notify
    assert "target" not in repeated_notify
    assert any("Replaced incorrect notify target notify.send_message" in fix for fix in fixes)
    assert any("Removed redundant target block from notify action" in fix for fix in fixes)


def test_autofix_adds_automation_domain_guard_template_condition():
    """Automation guard entities should use the current-attribute template guard."""
    prompt = "Don't run this if the washing machine cycle automation is already running."
    entities = [
        {
            "entity_id": "automation.washing_machine_cycle",
            "name": "Washing Machine Cycle",
            "domain": "automation",
            "state": "on",
        }
    ]
    entity_map = {
        "washing machine cycle": {
            "role": "guard",
            "entity_ids": ["automation.washing_machine_cycle"],
        }
    }
    yaml_text = """alias: Washing Machine
description: Example
triggers: []
conditions: []
actions:
  - action: notify.send_message
    data:
      message: "Done"
mode: single
"""

    fixed_yaml, fixes = autofix_yaml(yaml_text, prompt, entities, entity_map)
    parsed = yaml.safe_load(fixed_yaml)

    assert parsed["conditions"] == [
        {
            "condition": "template",
            "value_template": "{{ (state_attr('automation.washing_machine_cycle', 'current') | int(0)) == 0 }}",
        }
    ]
    assert any(
        "Injected missing guard condition for automation.washing_machine_cycle from entity map"
        in fix
        for fix in fixes
    )


def test_autofix_resolves_guard_and_notify_validation_issues_without_llm_repair():
    """Deterministic guard and notify fixes should satisfy validation."""
    prompt = "Don't run if either router LED switch is off. Notify my iPhone."
    entities = [
        {
            "entity_id": "switch.main_router_led",
            "name": "Main Router LED",
            "domain": "switch",
            "state": "off",
        },
        {
            "entity_id": "switch.mesh_mesh_led",
            "name": "Mesh Mesh LED",
            "domain": "switch",
            "state": "on",
        },
        {
            "entity_id": "notify.mobile_app_iphone_13",
            "name": "Notify iPhone 13",
            "domain": "notify",
        },
    ]
    entity_map = {
        "router led switches": {
            "role": "guard",
            "entity_ids": [
                "switch.main_router_led",
                "switch.mesh_mesh_led",
            ],
            "required_state": "on",
            "blocked_state": "off",
        },
        "my iphone": {
            "role": "notify_target",
            "entity_ids": ["notify.mobile_app_iphone_13"],
        },
    }
    yaml_text = """alias: Guards and Notify
description: Example
triggers: []
conditions: []
actions:
  - action: notify.send_message
    target:
      entity_id: notify.send_message
    data:
      message: "Router issue"
mode: single
"""

    fixed_yaml, _ = autofix_yaml(yaml_text, prompt, entities, entity_map)
    report = validate_generated_yaml(prompt, entities, fixed_yaml, entity_map)

    assert report.missing_entities == []
    assert report.structural_issues == []
