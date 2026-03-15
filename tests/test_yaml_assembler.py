"""Tests for deterministic YAML assembly from intent payloads."""

from __future__ import annotations

import yaml

from custom_components.automagic.yaml_assembler import assemble_yaml


def test_assemble_yaml_builds_ha_2024_10_sections_and_mired_values():
    """Assembler should emit valid top-level sections and normalize color_temp."""
    intent = {
        "alias": "Machine Timeout",
        "description": "Turns lights on, waits for completion, and notifies on timeout.",
        "mode": "restart",
        "triggers": [
            {
                "type": "state",
                "entity_id": "sensor.machine",
                "to": "running",
            }
        ],
        "conditions": [
            {
                "type": "time",
                "weekday": ["mon", "tue", "wed", "thu", "fri"],
            }
        ],
        "action_sequence": [
            {
                "step_type": "service_call",
                "action": "light.turn_on",
                "target_entity_ids": ["light.left", "light.right"],
                "data": {"kelvin": 2700, "brightness_pct": 20},
            },
            {
                "step_type": "wait_for_trigger",
                "wait_triggers": [
                    {
                        "type": "state",
                        "entity_id": "sensor.machine",
                        "to": "idle",
                    }
                ],
                "timeout": "02:00:00",
            },
            {
                "step_type": "choose",
                "choose_options": [
                    {
                        "conditions": [
                            {
                                "type": "template",
                                "value_template": "{{ not wait.completed }}",
                            }
                        ],
                        "sequence": [
                            {
                                "step_type": "service_call",
                                "action": "notify.mobile_app_phone",
                                "data": {"message": "Still running"},
                            }
                        ],
                    }
                ],
            },
        ],
    }

    yaml_text = assemble_yaml(intent)
    parsed = yaml.safe_load(yaml_text)

    assert "triggers:" in yaml_text
    assert "actions:" in yaml_text
    assert parsed["alias"] == "Machine Timeout"
    assert parsed["mode"] == "restart"
    assert parsed["conditions"][0]["weekday"] == ["mon", "tue", "wed", "thu", "fri"]
    assert parsed["actions"][0]["data"]["color_temp"] == 370
    assert "kelvin" not in parsed["actions"][0]["data"]
    assert parsed["actions"][1]["timeout"] == "02:00:00"
    assert parsed["actions"][1]["continue_on_timeout"] is True
    assert parsed["actions"][2]["choose"][0]["sequence"][0]["action"] == "notify.mobile_app_phone"


def test_assemble_yaml_keeps_targets_under_target_block():
    """Service targets should stay out of the action name."""
    intent = {
        "alias": "Scene Restore",
        "description": "Turns a light off and restores a scene.",
        "mode": "single",
        "triggers": [{"type": "time", "at": "21:30:00"}],
        "conditions": [],
        "action_sequence": [
            {
                "step_type": "service_call",
                "action": "light.turn_off",
                "target_entity_ids": ["light.bar_lamp"],
            },
            {
                "step_type": "scene",
                "scene_entity_id": "scene.evening",
            },
        ],
    }

    parsed = yaml.safe_load(assemble_yaml(intent))

    assert parsed["actions"][0] == {
        "action": "light.turn_off",
        "target": {"entity_id": ["light.bar_lamp"]},
    }
    assert parsed["actions"][1] == {
        "action": "scene.turn_on",
        "target": {"entity_id": "scene.evening"},
    }
