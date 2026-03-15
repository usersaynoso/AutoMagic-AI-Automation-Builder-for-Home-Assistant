"""Tests for intent schema validation helpers."""

from __future__ import annotations

from custom_components.automagic.intent_schema import (
    INTENT_JSON_SCHEMA,
    collect_intent_entity_ids,
    validate_intent,
)


def _valid_intent() -> dict:
    return {
        "alias": "Warm Lights",
        "description": "Turns on the bar lamp when the door opens.",
        "mode": "single",
        "triggers": [
            {
                "type": "state",
                "entity_id": "binary_sensor.front_door",
                "to": "on",
            }
        ],
        "conditions": [],
        "action_sequence": [
            {
                "step_type": "service_call",
                "action": "light.turn_on",
                "target_entity_ids": ["light.bar_lamp"],
                "data": {"brightness_pct": 20},
            }
        ],
    }


def test_validate_intent_accepts_minimal_valid_payload():
    """A simple service-call automation should validate cleanly."""
    valid, issues = validate_intent(_valid_intent())

    assert valid is True
    assert issues == []


def test_validate_intent_rejects_missing_triggers_and_service_action():
    """Validation should catch missing required trigger and action fields."""
    invalid_intent = _valid_intent()
    invalid_intent["triggers"] = []
    invalid_intent["action_sequence"] = [
        {
            "step_type": "service_call",
            "target_entity_ids": ["light.bar_lamp"],
        }
    ]

    valid, issues = validate_intent(invalid_intent)

    assert valid is False
    assert "intent.triggers must be a non-empty list." in issues
    assert (
        "intent.action_sequence[0].action is required for service_call steps."
        in issues
    )


def test_collect_intent_entity_ids_walks_nested_actions_and_conditions():
    """Entity collection should include nested choose, scene, and wait references."""
    intent = _valid_intent()
    intent["conditions"] = [
        {
            "type": "state",
            "entity_id": "switch.router_led",
            "state": "on",
        }
    ]
    intent["action_sequence"] = [
        {
            "step_type": "choose",
            "choose_options": [
                {
                    "conditions": [
                        {
                            "type": "state",
                            "entity_id": "sensor.washing_machine",
                            "state": "running",
                        }
                    ],
                    "sequence": [
                        {
                            "step_type": "service_call",
                            "action": "light.turn_on",
                            "target_entity_ids": [
                                "light.left",
                                "light.right",
                            ],
                        }
                    ],
                }
            ],
            "choose_default": [
                {
                    "step_type": "scene",
                    "scene_entity_id": "scene.evening",
                }
            ],
        },
        {
            "step_type": "wait_for_trigger",
            "wait_triggers": [
                {
                    "type": "state",
                    "entity_id": "vacuum.janet",
                    "to": "docked",
                }
            ],
        },
    ]

    entity_ids = collect_intent_entity_ids(intent)

    assert entity_ids == {
        "binary_sensor.front_door",
        "switch.router_led",
        "sensor.washing_machine",
        "light.left",
        "light.right",
        "scene.evening",
        "vacuum.janet",
    }


def test_intent_json_schema_mentions_required_wrapper_keys():
    """The injected schema should describe the public response contract."""
    assert '"intent"' in INTENT_JSON_SCHEMA
    assert '"summary"' in INTENT_JSON_SCHEMA
    assert '"AutomationIntent"' in INTENT_JSON_SCHEMA
